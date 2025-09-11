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
    INSURANCE_ASSISTANT,
)

load_dotenv()

DEFAULT_ASSISTANT = "INTERVIEW_SCHEDULING_AGENT"
ASSISTANT_TYPES = {
    "Interview Scheduling": INTERVIEW_SCHEDULING_AGENT,
    "Interview Screening": INTERVIEW_SCREENING_AGENT,
    "Resume Update": RESUME_UPDATE_AGENT,
    "Real Estate": REAL_ESTATE_AGENT,
    "Customer Support": CUSTOMER_SUPPORT_AGENT,
    "Banking Support": BANKING_SUPPORT_AGENT,
    "Healthcare": HEALTHCARE_AGENT,
    "Insurance Policy Agent": INSURANCE_ASSISTANT,
}

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
    def format_phone_number(country_code: str, phone_number: str):
        try:
            cleaned_number = "".join(filter(str.isdigit, phone_number))
            full_number = f"{country_code}{cleaned_number}"
            parsed_number = phonenumbers.parse(full_number)
            if not phonenumbers.is_valid_number(parsed_number):
                raise gr.Error("Invalid phone number")
            return phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
        except Exception as e:
            raise gr.Error(f"Error: {str(e)}")


class UltravoxCallManager:
    def __init__(self):
        self.env_vars = {
            "ULTRAVOX_API_KEY": os.getenv("ULTRAVOX_API_KEY"),
            "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID"),
            "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN"),
            "TWILIO_PHONE_NUMBER": os.getenv("TWILIO_PHONE_NUMBER"),
        }

    def initiate_call(self, system_prompt, country_code, phone_number):
        gr.Info("Validating phone number...")
        formatted_number = PhoneNumberValidator.format_phone_number(country_code, phone_number)

        gr.Info("Creating Ultravox call...")
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
                headers={"Content-Type": "application/json", "X-API-Key": self.env_vars["ULTRAVOX_API_KEY"]},
                json=call_config,
            )
            response.raise_for_status()
            join_url = response.json().get("joinUrl")
            if not join_url:
                raise gr.Error("Failed to create call")
        except requests.exceptions.RequestException as e:
            raise gr.Error(str(e))

        gr.Info("Initiating Twilio call...")
        try:
            client = Client(self.env_vars["TWILIO_ACCOUNT_SID"], self.env_vars["TWILIO_AUTH_TOKEN"])
            call = client.calls.create(
                twiml=f'<Response><Connect><Stream url="{join_url}"/></Connect></Response>',
                to=formatted_number,
                from_=self.env_vars["TWILIO_PHONE_NUMBER"],
                record=True,
            )
            gr.Success(f"Call initiated! Call SID: {call.sid}")
        except Exception as e:
            raise gr.Error(str(e))


class UltravoxInterface:
    def __init__(self):
        self.call_manager = UltravoxCallManager()

    def update_prompt(self, selected_type):
        return ASSISTANT_TYPES[selected_type]

    def create_interface(self):
        with gr.Blocks(theme="soft") as interface:
            gr.Markdown("# 📞 Ultravox <> Twilio", elem_classes="text-3xl font-bold text-center")

            with gr.Row():
                choices = list(ASSISTANT_TYPES.keys())
                assistant_type = gr.Dropdown(choices=choices, label="Call Type", value=choices[0], interactive=True, elem_classes="w-full")
            with gr.Row():
                country_code = gr.Dropdown(
                    choices=[f"{c['name']} ({c['code']})" for c in COUNTRY_CODES],
                    label="Country Code",
                    value=f"{COUNTRY_CODES[0]['name']} ({COUNTRY_CODES[0]['code']})",
                    elem_classes="w-1/3",
                )
                phone_number = gr.Textbox(label="Mobile Number", placeholder="Enter mobile number without country code", max_lines=1, elem_classes="w-2/3")

            system_prompt = gr.TextArea(
                label="Call Prompt", lines=8, value=ASSISTANT_TYPES["Interview Scheduling"], elem_classes="w-full border border-gray-300 p-2 rounded-lg"
            )

            with gr.Row():
                submit_btn = gr.Button("📞 Initiate Call", variant="primary", elem_classes="w-1/2 bg-blue-600 text-white")
                clear_btn = gr.Button("🧹 Clear", variant="secondary", elem_classes="w-1/2 bg-gray-400 text-white")

            def get_country_code(selection):
                return selection.split("(")[1].strip(")")

            assistant_type.change(fn=self.update_prompt, inputs=[assistant_type], outputs=[system_prompt])

            submit_btn.click(
                fn=lambda p, c, n: self.call_manager.initiate_call(p, get_country_code(c), n), inputs=[system_prompt, country_code, phone_number], outputs=[]
            )

            clear_btn.click(fn=lambda: [COUNTRY_CODES[0]["code"], "", ""], inputs=[], outputs=[country_code, phone_number, system_prompt])

        return interface


def main():
    app = UltravoxInterface()
    interface = app.create_interface()
    interface.launch()


if __name__ == "__main__":
    main()
