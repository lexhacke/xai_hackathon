import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

class WhatsAppEndpoint:
    def __init__(self, number):
        self.number = number
        self.client = Client(os.environ.get('TWILIO_SID'), os.environ.get('TWILIO_SECRET'))

    def send(self, body, media=[]):
        self.client.messages.create(
            from_='whatsapp:+14155238886',  # Twilio Sandbox Number
            body=body,
            media_url=media,
            to='whatsapp:+18584423152'      # Your personal number
        )

if __name__ == "__main__":
    endpoint = WhatsAppEndpoint('+18584423152')
    endpoint.send(r"Hello from \xai\backend\app\core\twilio_api.py!", ['https://preview.redd.it/nahhh-bro-pushin-way-too-hard-v0-79f7xt8veqb81.jpg?width=1080&crop=smart&auto=webp&s=fa0190f05a8e0f0034437c26b69bfc7b3d890e0e'])