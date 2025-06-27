# Add this at the beginning of the file after imports
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add this to the main execution block
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
            import pandas as pd
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
