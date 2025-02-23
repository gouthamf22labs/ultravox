import gradio as gr
import os
from twilio.rest import Client
import requests
from dotenv import load_dotenv
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


def create_ultravox_call(system_prompt, phone_number):
    env_vars = {
        "ULTRAVOX_API_KEY": os.getenv("ULTRAVOX_API_KEY"),
        "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID"),
        "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN"),
        "TWILIO_PHONE_NUMBER": os.getenv("TWILIO_PHONE_NUMBER"),
    }

    if not all(env_vars.values()):
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
            "https://api.ultravox.ai/api/calls", headers={"Content-Type": "application/json", "X-API-Key": env_vars["ULTRAVOX_API_KEY"]}, json=call_config
        )
        response.raise_for_status()
        return "Success", response.json().get("joinUrl")
    except requests.exceptions.RequestException as e:
        return f"Error: {str(e)}", None


def initiate_call(system_prompt: str, phone_number: str):
    if not all([system_prompt, phone_number]):
        return "Error: Please fill in all fields"

    status, join_url = create_ultravox_call(system_prompt, phone_number)
    if not join_url:
        return status

    try:
        client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
        call = client.calls.create(
            twiml=f'<Response><Connect><Stream url="{join_url}"/></Connect></Response>', to=phone_number, from_=os.getenv("TWILIO_PHONE_NUMBER")
        )
        return f"Success: Call initiated (SID: {call.sid})"
    except Exception as e:
        return f"Error: {str(e)}"


def get_prompt(assistant_type: str) -> str:
    """Get the appropriate prompt based on selection"""
    assistants = {
        "INTERVIEW_SCHEDULING_AGENT": INTERVIEW_SCHEDULING_AGENT,
        "INTERVIEW_SCREENING_AGENT": INTERVIEW_SCREENING_AGENT,
        "RESUME_UPDATE_AGENT": RESUME_UPDATE_AGENT,
        "REAL_ESTATE_AGENT": REAL_ESTATE_AGENT,
        "CUSTOMER_SUPPORT_AGENT": CUSTOMER_SUPPORT_AGENT,
        "BANKING_SUPPORT_AGENT": BANKING_SUPPORT_AGENT,
        "HEALTHCARE_AGENT": HEALTHCARE_AGENT,
    }
    return assistants.get(assistant_type, INTERVIEW_SCHEDULING_AGENT)


def create_interface():
    with gr.Blocks(title="ULTRAVOX") as interface:
        gr.Markdown("# ULTRAVOX")

        with gr.Row():
            assistant_type = gr.Dropdown(
                choices=[
                    "INTERVIEW_SCHEDULING_AGENT",
                    "INTERVIEW_SCREENING_AGENT",
                    "RESUME_UPDATE_AGENT",
                    "REAL_ESTATE_AGENT",
                    "CUSTOMER_SUPPORT_AGENT",
                    "BANKING_SUPPORT_AGENT",
                    "HEALTHCARE_AGENT",
                ],
                label="Select Call Type",
            )

            phone_number = gr.Textbox(label="Phone Number", placeholder="Enter phone number with country code")

        system_prompt = gr.TextArea(label="Prompt - Edit as per your need.", lines=10)
        assistant_type.change(fn=get_prompt, inputs=[assistant_type], outputs=[system_prompt])

        with gr.Row():
            submit_btn = gr.Button("Initiate Call", variant="primary")
            clear_btn = gr.Button("Clear", variant="secondary")

        output = gr.Textbox(label="Status", interactive=False)

        submit_btn.click(fn=initiate_call, inputs=[system_prompt, phone_number], outputs=[output])

        clear_btn.click(fn=lambda: ["", ""], inputs=[], outputs=[phone_number, output])

    return interface


if __name__ == "__main__":
    interface = create_interface()
    interface.launch(share=True)