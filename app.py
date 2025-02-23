import gradio as gr
import os
from twilio.rest import Client
import requests
from dotenv import load_dotenv
import phonenumbers
from assistants import (
    INTERVIEW_SCHEDULING_AGENT,
    INTERVIEW_SCREENING_AGENT,
    RESUME_UPDATE_AGENT,
    REAL_ESTATE_AGENT,
    CUSTOMER_SUPPORT_AGENT,
    BANKING_SUPPORT_AGENT,
    HEALTHCARE_AGENT,
)

load_dotenv()

# Constants
DEFAULT_ASSISTANT = "INTERVIEW_SCHEDULING_AGENT"
ASSISTANT_TYPES = {
    "INTERVIEW_SCHEDULING_AGENT": INTERVIEW_SCHEDULING_AGENT,
    "INTERVIEW_SCREENING_AGENT": INTERVIEW_SCREENING_AGENT,
    "RESUME_UPDATE_AGENT": RESUME_UPDATE_AGENT,
    "REAL_ESTATE_AGENT": REAL_ESTATE_AGENT,
    "CUSTOMER_SUPPORT_AGENT": CUSTOMER_SUPPORT_AGENT,
    "BANKING_SUPPORT_AGENT": BANKING_SUPPORT_AGENT,
    "HEALTHCARE_AGENT": HEALTHCARE_AGENT,
}

# Country codes for dropdown
COUNTRY_CODES = [
    {"name": "India", "code": "+91"},
    {"name": "United States", "code": "+1"},
    {"name": "United Kingdom", "code": "+44"},
    {"name": "Canada", "code": "+1"},
    {"name": "Australia", "code": "+61"},
    {"name": "Germany", "code": "+49"},
    {"name": "France", "code": "+33"},
    {"name": "Japan", "code": "+81"},
    {"name": "China", "code": "+86"},
    {"name": "Singapore", "code": "+65"},
]

class PhoneNumberValidator:
    @staticmethod
    def format_phone_number(country_code: str, phone_number: str) -> tuple[bool, str]:
        """
        Validate and format the phone number with country code
        Returns: (is_valid, formatted_number) tuple
        """
        try:
            # Remove any spaces or special characters from phone number
            cleaned_number = ''.join(filter(str.isdigit, phone_number))
            
            # Combine country code and number
            full_number = f"{country_code}{cleaned_number}"
            
            # Parse and validate the number
            parsed_number = phonenumbers.parse(full_number)
            if not phonenumbers.is_valid_number(parsed_number):
                return False, "Invalid phone number"
                
            # Format in E.164 format
            formatted_number = phonenumbers.format_number(
                parsed_number, 
                phonenumbers.PhoneNumberFormat.E164
            )
            return True, formatted_number
            
        except Exception as e:
            return False, f"Error: {str(e)}"

class UltravoxCallManager:
    def __init__(self):
        self.env_vars = {
            "ULTRAVOX_API_KEY": os.getenv("ULTRAVOX_API_KEY"),
            "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID"),
            "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN"),
            "TWILIO_PHONE_NUMBER": os.getenv("TWILIO_PHONE_NUMBER"),
        }

    def create_call(self, system_prompt, phone_number):
        if not all(self.env_vars.values()):
            return "Error: Missing environment variables", None

        call_config = {
            "systemPrompt": system_prompt,
            "model": "fixie-ai/ultravox",
            "voice": "Riya-Hindi-Urdu",
            "temperature": 0.3,
            "firstSpeaker": "FIRST_SPEAKER_USER",
            "medium": {"twilio": {}},
        }

        try:
            response = requests.post(
                "https://api.ultravox.ai/api/calls",
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": self.env_vars["ULTRAVOX_API_KEY"]
                },
                json=call_config
            )
            response.raise_for_status()
            return "Success", response.json().get("joinUrl")
        except requests.exceptions.RequestException as e:
            return f"Error: {str(e)}", None

    def initiate_call(self, system_prompt: str, country_code: str, phone_number: str):
        if not all([system_prompt, country_code, phone_number]):
            return "Error: Please fill in all fields"

        # Validate and format phone number
        is_valid, formatted_number = PhoneNumberValidator.format_phone_number(
            country_code, phone_number
        )
        if not is_valid:
            return formatted_number

        status, join_url = self.create_call(system_prompt, formatted_number)
        if not join_url:
            return status

        try:
            client = Client(
                self.env_vars["TWILIO_ACCOUNT_SID"],
                self.env_vars["TWILIO_AUTH_TOKEN"]
            )
            call = client.calls.create(
                twiml=f'<Response><Connect><Stream url="{join_url}"/></Connect></Response>',
                to=formatted_number,
                from_=self.env_vars["TWILIO_PHONE_NUMBER"]
            )
            return f"Success: Call initiated (SID: {call.sid})"
        except Exception as e:
            return f"Error: {str(e)}"

class UltravoxInterface:
    def __init__(self):
        self.call_manager = UltravoxCallManager()

    def get_prompt(self, assistant_type: str) -> str:
        """Get the appropriate prompt based on selection"""
        return ASSISTANT_TYPES.get(assistant_type, ASSISTANT_TYPES[DEFAULT_ASSISTANT])

    def clear_fields(self):
        """Clear the input fields"""
        return [COUNTRY_CODES[0]["code"], "", ""]  # Reset to first country code

    def create_interface(self):
        """Create the Gradio interface"""
        with gr.Blocks() as interface:
            gr.Markdown("# Ultravox <> Twilio")

            with gr.Row():
                assistant_type = gr.Dropdown(
                    choices=list(ASSISTANT_TYPES.keys()),
                    label="Select Call Type",
                    value=DEFAULT_ASSISTANT
                )

            with gr.Row():
                country_code = gr.Dropdown(
                    choices=[f"{c['name']} ({c['code']})" for c in COUNTRY_CODES],
                    label="Country Code",
                    value=f"{COUNTRY_CODES[0]['name']} ({COUNTRY_CODES[0]['code']})"                )
                phone_number = gr.Textbox(
                    label="Mobile Number",
                    placeholder="Enter mobile number without country code",
                    max_lines=1
                )

            system_prompt = gr.TextArea(
                label="Prompt - Edit as per your need.",
                lines=10,
                value=ASSISTANT_TYPES[DEFAULT_ASSISTANT]
            )

            assistant_type.change(
                fn=self.get_prompt,
                inputs=[assistant_type],
                outputs=[system_prompt]
            )

            with gr.Row():
                submit_btn = gr.Button("Initiate Call", variant="primary")
                clear_btn = gr.Button("Clear", variant="secondary")

            output = gr.Textbox(label="Status", interactive=False)

            # Extract country code from selection
            def get_country_code(selection):
                return selection.split('(')[1].strip(')')

            submit_btn.click(
                fn=lambda p, c, n: self.call_manager.initiate_call(
                    p, get_country_code(c), n
                ),
                inputs=[system_prompt, country_code, phone_number],
                outputs=[output]
            )

            clear_btn.click(
                fn=self.clear_fields,
                inputs=[],
                outputs=[country_code, phone_number, output]
            )

        return interface

def main():
    app = UltravoxInterface()
    interface = app.create_interface()
    interface.launch()

if __name__ == "__main__":
    main()