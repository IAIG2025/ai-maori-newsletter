import requests
from bs4 import BeautifulSoup
import feedparser
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import time
import os
from dataclasses import dataclass, asdict
from typing import List, Dict
import openai
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import pandas as pd

# Load environment variables
load_dotenv()

@dataclass
class NewsItem:
    title: str
    url: str
    summary: str
    source: str
    published_date: str
    relevance_score: float
    tags: List[str]

class NewsletterBot:
    def __init__(self):
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.gmail_user = os.getenv('GMAIL_USER')
        self.gmail_password = os.getenv('GMAIL_APP_PASSWORD')  # Use App Password
        self.google_sheets_creds = os.getenv('GOOGLE_SHEETS_CREDS_PATH')
        
        # Content sources configuration
        self.sources = {
            'rss_feeds': [
                'https://www.technologyreview.com/feed/',
                'https://techcrunch.com/category/artificial-intelligence/feed/',
                'https://venturebeat.com/ai/feed/',
                'https://feeds.feedburner.com/oreilly/radar'
            ],
            'websites': [
                {
                    'url': 'https://www.tepunikokiri.govt.nz',
                    'selector': 'article h2 a',  # CSS selector for headlines
                    'name': 'Te Puni Kōkiri'
                },
                {
                    'url': 'https://www.digital.govt.nz',
                    'selector': '.news-item h3 a',
                    'name': 'Digital Government NZ'
                }
            ]
        }
        
        # Initialize OpenAI
        if self.openai_api_key:
            openai.api_key = self.openai_api_key

    def scrape_rss_feeds(self) -> List[NewsItem]:
        """Scrape content from RSS feeds"""
        news_items = []
        
        for feed_url in self.sources['rss_feeds']:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:5]:  # Limit to 5 most recent
                    # Get published date
                    pub_date = entry.get('published', datetime.now().isoformat())
                    
                    # Create news item
                    item = NewsItem(
                        title=entry.title,
                        url=entry.link,
                        summary=entry.get('summary', '')[:300],
                        source=feed.feed.get('title', 'Unknown'),
                        published_date=pub_date,
                        relevance_score=0.0,
                        tags=[]
                    )
                    news_items.append(item)
                    
            except Exception as e:
                print(f"Error scraping RSS feed {feed_url}: {e}")
                
        return news_items

    def scrape_websites(self) -> List[NewsItem]:
        """Scrape content from specific websites"""
        news_items = []
        
        for site in self.sources['websites']:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = requests.get(site['url'], headers=headers, timeout=10)
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Find articles using CSS selector
                articles = soup.select(site['selector'])[:5]
                
                for article in articles:
                    title = article.get_text().strip()
                    url = article.get('href', '')
                    
                    # Make URL absolute if relative
                    if url.startswith('/'):
                        url = site['url'].rstrip('/') + url
                    
                    item = NewsItem(
                        title=title,
                        url=url,
                        summary='',
                        source=site['name'],
                        published_date=datetime.now().isoformat(),
                        relevance_score=0.0,
                        tags=[]
                    )
                    news_items.append(item)
                    
            except Exception as e:
                print(f"Error scraping website {site['name']}: {e}")
                
        return news_items

    def analyze_relevance(self, news_items: List[NewsItem]) -> List[NewsItem]:
        """Use AI to analyze relevance to AI + Māori topics"""
        if not self.openai_api_key:
            print("No OpenAI API key found, skipping AI analysis")
            return news_items
        
        for item in news_items:
            try:
                prompt = f"""
                Analyze this news article for relevance to AI technology and Māori/Indigenous topics.
                
                Title: {item.title}
                Summary: {item.summary}
                Source: {item.source}
                
                Rate relevance on a scale of 0-10 where:
                - 10: Directly about AI AND Māori/Indigenous topics
                - 7-9: Strongly related to AI with Indigenous connections
                - 4-6: General AI news that could be relevant
                - 1-3: Tangentially related
                - 0: Not relevant
                
                Also provide 2-3 relevant tags.
                
                Respond in JSON format:
                {
                    "relevance_score": 0-10,
                    "tags": ["tag1", "tag2", "tag3"],
                    "reasoning": "brief explanation"
                }
                """
                
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200
                )
                
                result = json.loads(response.choices[0].message.content)
                item.relevance_score = result.get('relevance_score', 0)
                item.tags = result.get('tags', [])
                
            except Exception as e:
                print(f"Error analyzing item {item.title}: {e}")
                item.relevance_score = 5.0  # Default score
                
        return news_items

    def filter_and_rank_content(self, news_items: List[NewsItem]) -> List[NewsItem]:
        """Filter content by relevance and remove duplicates"""
        # Remove duplicates by URL
        seen_urls = set()
        unique_items = []
        for item in news_items:
            if item.url not in seen_urls:
                seen_urls.add(item.url)
                unique_items.append(item)
        
        # Filter by relevance score (keep items with score >= 4)
        relevant_items = [item for item in unique_items if item.relevance_score >= 4.0]
        
        # Sort by relevance score (highest first)
        relevant_items.sort(key=lambda x: x.relevance_score, reverse=True)
        
        return relevant_items[:15]  # Keep top 15 items

    def generate_newsletter_html(self, news_items: List[NewsItem]) -> str:
        """Generate HTML newsletter content"""
        current_date = datetime.now().strftime("%B %d, %Y")
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>AI & Māori Weekly - {current_date}</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #1e3a8a, #7c3aed); color: white; padding: 30px; border-radius: 8px; text-align: center; }}
                .article {{ border-left: 4px solid #7c3aed; padding: 15px; margin: 20px 0; background: #f8fafc; }}
                .article h3 {{ margin-top: 0; color: #1e293b; }}
                .article .meta {{ color: #64748b; font-size: 14px; margin-bottom: 10px; }}
                .tags {{ margin-top: 10px; }}
                .tag {{ background: #e0e7ff; color: #3730a3; padding: 4px 8px; border-radius: 12px; font-size: 12px; margin-right: 5px; }}
                .footer {{ text-align: center; margin-top: 40px; padding: 20px; background: #f1f5f9; border-radius: 8px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>AI & Māori Weekly</h1>
                <p>Artificial Intelligence insights for Māori organisations</p>
                <p>{current_date}</p>
            </div>
            
            <div style="margin: 30px 0;">
                <p>Kia ora! Here are this week's most relevant AI developments for Māori organisations and communities.</p>
            </div>
        """
        
        # Add high relevance items first
        high_relevance = [item for item in news_items if item.relevance_score >= 7]
        if high_relevance:
            html_content += "<h2 style='color: #7c3aed; border-bottom: 2px solid #7c3aed; padding-bottom: 5px;'>🔥 Top Stories</h2>"
            for item in high_relevance:
                html_content += self._format_article_html(item)
        
        # Add other relevant items
        other_items = [item for item in news_items if item.relevance_score < 7]
        if other_items:
            html_content += "<h2 style='color: #1e3a8a; border-bottom: 2px solid #1e3a8a; padding-bottom: 5px;'>📰 AI News & Updates</h2>"
            for item in other_items:
                html_content += self._format_article_html(item)
        
        html_content += """
            <div class="footer">
                <p>This newsletter is powered by AI content curation.</p>
                <p>Questions or feedback? Reply to this email.</p>
                <p><a href="[UNSUBSCRIBE_LINK]">Unsubscribe</a></p>
            </div>
        </body>
        </html>
        """
        
        return html_content

    def _format_article_html(self, item: NewsItem) -> str:
        """Format individual article for HTML newsletter"""
        tags_html = ' '.join([f'<span class="tag">{tag}</span>' for tag in item.tags])
        
        return f"""
        <div class="article">
            <h3><a href="{item.url}" style="color: #1e293b; text-decoration: none;">{item.title}</a></h3>
            <div class="meta">Source: {item.source} | Relevance: {item.relevance_score}/10</div>
            {f'<p>{item.summary}</p>' if item.summary else ''}
            <div class="tags">{tags_html}</div>
        </div>
        """

    def save_to_google_sheets(self, news_items: List[NewsItem]):
        """Save curated content to Google Sheets for review"""
        try:
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name(self.google_sheets_creds, scope)
            client = gspread.authorize(creds)
            
            # Open or create spreadsheet
            try:
                sheet = client.open("AI Māori Newsletter Content").sheet1
            except gspread.SpreadsheetNotFound:
                spreadsheet = client.create("AI Māori Newsletter Content")
                sheet = spreadsheet.sheet1
                # Add headers
                sheet.append_row(['Date', 'Title', 'URL', 'Source', 'Relevance Score', 'Tags', 'Summary'])
            
            # Add content
            for item in news_items:
                sheet.append_row([
                    datetime.now().strftime("%Y-%m-%d"),
                    item.title,
                    item.url,
                    item.source,
                    item.relevance_score,
                    ', '.join(item.tags),
                    item.summary[:200]  # Truncate for sheets
                ])
                
        except Exception as e:
            print(f"Error saving to Google Sheets: {e}")

    def send_newsletter(self, html_content: str, recipient_list: List[str]):
        """Send newsletter via Gmail SMTP"""
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(self.gmail_user, self.gmail_password)
            
            for recipient in recipient_list:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = f"AI & Māori Weekly - {datetime.now().strftime('%B %d, %Y')}"
                msg['From'] = self.gmail_user
                msg['To'] = recipient
                
                html_part = MIMEText(html_content, 'html')
                msg.attach(html_part)
                
                server.send_message(msg)
                print(f"Newsletter sent to {recipient}")
                
            server.quit()
            
        except Exception as e:
            print(f"Error sending newsletter: {e}")

    def run_weekly_collection(self):
        """Main method to run the weekly content collection and newsletter generation"""
        print(f"Starting weekly content collection - {datetime.now()}")
        
        # Collect content
        all_items = []
        all_items.extend(self.scrape_rss_feeds())
        all_items.extend(self.scrape_websites())
        
        print(f"Collected {len(all_items)} initial items")
        
        # Analyze relevance
        analyzed_items = self.analyze_relevance(all_items)
        
        # Filter and rank
        final_items = self.filter_and_rank_content(analyzed_items)
        
        print(f"Final curated list: {len(final_items)} items")
        
        # Save to Google Sheets for review
        self.save_to_google_sheets(final_items)
        
        # Generate newsletter
        newsletter_html = self.generate_newsletter_html(final_items)
        
        # Save newsletter to file for review
        with open(f'newsletter_{datetime.now().strftime("%Y%m%d")}.html', 'w', encoding='utf-8') as f:
            f.write(newsletter_html)
        
        print("Newsletter generated and saved for review")
        
        return final_items, newsletter_html

# Example usage and scheduler setup
# Example usage and scheduler setup
if __name__ == "__main__":
    bot = NewsletterBot()
    
    # Check if running in test mode
    test_mode = os.getenv('TEST_MODE', 'false').lower() == 'true'
    
    if test_mode:
        print("Running in TEST MODE - newsletter will be saved to file only")
    
    # Generate newsletter
    items, newsletter = bot.run_weekly_collection()
    
    if not test_mode and items:
        # Load subscribers and send newsletter
        try:
            # Try to load subscribers from CSV
            if os.path.exists('subscribers.csv'):
                subscribers_df = pd.read_csv('subscribers.csv')
                active_subscribers = subscribers_df[
                    subscribers_df.get('status', 'active') == 'active'
                ]['email'].tolist()
                
                if active_subscribers:
                    bot.send_newsletter(newsletter, active_subscribers)
                    print(f"Newsletter sent to {len(active_subscribers)} subscribers")
                else:
                    print("No active subscribers found")
            else:
                print("No subscribers.csv file found")
                
        except Exception as e:
            print(f"Error sending newsletter: {e}")
    
    print(f"Newsletter generation completed with {len(items)} items")
