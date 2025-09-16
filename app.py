from typing import Dict, List, Optional, Any, Tuple
import gradio as gr
import os
import plivo
from twilio.rest import Client
import requests
from dotenv import load_dotenv
import phonenumbers
import pandas as pd
import re
import time
import threading
import logging
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

load_dotenv(override=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    def format_phone_number(country_code: str, phone_number: str) -> str:
        """Format and validate phone number."""
        try:
            if not country_code.startswith('+'):
                country_code = f"+{country_code}"

            full_number = f"{country_code}{phone_number}"
            parsed_number = phonenumbers.parse(full_number, None)

            if not phonenumbers.is_valid_number(parsed_number):
                raise gr.Error(f"Invalid phone number: {full_number}")

            return phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)

        except Exception as e:
            logger.error(f"Phone validation error: {str(e)}")
            raise gr.Error(f"Error: {str(e)}")


class TemplateProcessor:
    """Handles template variable processing and CSV operations."""

    @staticmethod
    def extract_variables(text: str) -> List[str]:
        """Extract template variables from text in the format {{variable_name}}."""
        pattern = r'\{\{([^}]+)\}\}'
        variables = re.findall(pattern, text)
        return list(set(variables))

    @staticmethod
    def replace_variables(template: str, variables: Dict[str, Any]) -> str:
        """Replace template variables with actual values."""
        if not isinstance(template, str):
            template = str(template)

        result = template
        for key, value in variables.items():
            if isinstance(key, str):
                pattern = f"{{{{{key}}}}}"
                replacement = str(value) if value is not None else ""
                result = result.replace(pattern, replacement)
        return result


class BatchProcessor:
    """Handles batch call processing with CSV data."""

    def __init__(self, call_manager):
        self.call_manager = call_manager
        self.batch_status: Dict[str, int] = {}
        self.batch_results: List[Dict[str, Any]] = []
        self.is_processing = False
        self._thread: Optional[threading.Thread] = None

    def validate_csv_data(self, csv_data: pd.DataFrame) -> Tuple[bool, str]:
        """Validate CSV data has required columns."""
        required_columns = ['phone_number', 'country_code']
        missing_columns = [col for col in required_columns if col not in csv_data.columns]

        if missing_columns:
            return False, f"CSV must contain columns: {', '.join(missing_columns)}"
        return True, ""

    def process_batch_calls(
        self,
        provider: str,
        system_prompt: str,
        csv_data: pd.DataFrame,
        delay: int = 2
    ) -> List[Dict[str, Any]]:
        """Process batch calls from CSV data."""
        logger.info(f"Starting batch processing: {len(csv_data)} calls with {provider}")

        self.is_processing = True
        self.batch_results = []
        self.batch_status = {
            "current": 0,
            "total": len(csv_data),
            "completed": 0,
            "failed": 0
        }

        for index, row in csv_data.iterrows():
            if not self.is_processing:
                break

            try:
                self.batch_status["current"] = index + 1

                # Extract variables from row
                variables = {column: row[column] for column in row.index}

                # Replace template variables in system prompt
                personalized_prompt = TemplateProcessor.replace_variables(
                    system_prompt, variables
                )

                phone_number = str(row['phone_number'])
                country_code = str(row['country_code'])

                # Make the call
                try:
                    call_id = self.call_manager.initiate_call(
                        provider, personalized_prompt, country_code, phone_number
                    )
                    result = {
                        "row": index + 1,
                        "status": "success",
                        "phone": phone_number,
                        "ultravox_call_id": call_id
                    }
                    self.batch_status["completed"] += 1
                except Exception as call_error:
                    logger.error(f"Call failed for {phone_number}: {str(call_error)}")
                    result = {
                        "row": index + 1,
                        "status": "failed",
                        "error": str(call_error),
                        "phone": phone_number
                    }
                    self.batch_status["failed"] += 1

                self.batch_results.append(result)
                time.sleep(delay)

            except Exception as e:
                logger.error(f"Row processing error: {str(e)}")
                result = {"row": index + 1, "status": "failed", "error": str(e)}
                self.batch_results.append(result)
                self.batch_status["failed"] += 1

        self.is_processing = False
        logger.info(
            f"Batch processing completed! "
            f"Success: {self.batch_status.get('completed', 0)}, "
            f"Failed: {self.batch_status.get('failed', 0)}"
        )
        return self.batch_results

    def start_async_processing(
        self,
        provider: str,
        system_prompt: str,
        csv_data: pd.DataFrame,
        delay: int = 2
    ) -> str:
        """Start batch processing in a separate thread."""
        if self.is_processing:
            return "❌ Batch processing already running"

        is_valid, error_msg = self.validate_csv_data(csv_data)
        if not is_valid:
            return f"❌ {error_msg}"

        def run_batch():
            return self.process_batch_calls(provider, system_prompt, csv_data, delay)

        self._thread = threading.Thread(target=run_batch)
        self._thread.start()
        return "🚀 Batch processing started! Check the progress below."

    def stop_processing(self) -> str:
        """Stop the batch processing."""
        logger.info("Batch processing stopped by user")
        self.is_processing = False
        return "🛑 Batch processing stopped"

    def get_status(self) -> str:
        """Get current batch processing status."""
        if not self.batch_status:
            return "No batch processing running"

        return (
            f"Processing: {self.batch_status.get('current', 0)}/"
            f"{self.batch_status.get('total', 0)} | "
            f"Completed: {self.batch_status.get('completed', 0)} | "
            f"Failed: {self.batch_status.get('failed', 0)}"
        )

    def get_results(self) -> List[Dict[str, Any]]:
        """Get batch processing results."""
        return self.batch_results



class UltravoxCallManager:
    """Manages Ultravox API calls and provider integrations."""

    def __init__(self):
        self.env_vars = {
            "ULTRAVOX_API_KEY": os.getenv("ULTRAVOX_API_KEY"),
            "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID"),
            "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN"),
            "TWILIO_PHONE_NUMBER": os.getenv("TWILIO_PHONE_NUMBER"),
            "PLIVO_AUTH_ID": os.getenv("PLIVO_AUTH_ID"),
            "PLIVO_AUTH_TOKEN": os.getenv("PLIVO_AUTH_TOKEN"),
            "PLIVO_PHONE_NUMBER": os.getenv("PLIVO_PHONE_NUMBER"),
        }

    def _create_ultravox_call(self, system_prompt: str, provider: str) -> str:
        """Create a call via Ultravox API and return join URL."""
        call_config = {
            "systemPrompt": system_prompt,
            "model": "fixie-ai/ultravox",
            "voice": "Monika-English-Indian",
            "temperature": 0.3,
            "firstSpeaker": "FIRST_SPEAKER_AGENT",
            "medium": {provider.lower(): {}},
            "recordingEnabled": True,
        }

        try:
            response = requests.post(
                "https://api.ultravox.ai/api/calls",
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": self.env_vars["ULTRAVOX_API_KEY"],
                },
                json=call_config,
            )
            response.raise_for_status()
            response_data = response.json()
            join_url = response_data.get("joinUrl")
            call_id = response_data.get("callId")
            
            logger.info(f"Ultravox Call ID: {call_id}")
            print(f"Ultravox Call ID: {call_id}")  # Also print to ensure visibility

            if not join_url:
                raise gr.Error("Failed to create call")
            return join_url, call_id

        except requests.exceptions.RequestException as e:
            logger.error(f"Ultravox API error: {str(e)}")
            raise gr.Error(str(e))

    def _initiate_twilio_call(self, join_url: str, formatted_number: str) -> None:
        """Initiate call via Twilio."""
        gr.Info("Initiating Twilio call...")
        try:
            client = Client(
                self.env_vars["TWILIO_ACCOUNT_SID"],
                self.env_vars["TWILIO_AUTH_TOKEN"]
            )
            call = client.calls.create(
                twiml=f'<Response><Connect><Stream url="{join_url}"/></Connect></Response>',
                to=formatted_number,
                from_=self.env_vars["TWILIO_PHONE_NUMBER"],
                record=True,
            )
            gr.Success(f"Twilio call initiated! Call SID: {call.sid}")
        except Exception as e:
            logger.error(f"Twilio error: {str(e)}")
            raise gr.Error(str(e))

    def _initiate_plivo_call(self, join_url: str, formatted_number: str) -> None:
        """Initiate call via Plivo."""
        try:
            client = plivo.RestClient(
                auth_id=self.env_vars["PLIVO_AUTH_ID"],
                auth_token=self.env_vars["PLIVO_AUTH_TOKEN"]
            )
            client.calls.create(
                from_=self.env_vars["PLIVO_PHONE_NUMBER"],
                to_=formatted_number,
                answer_url=f"https://hari-tools.f22labs.dev/webhook/plivo-ans?joinUrl={join_url}",
                answer_method="GET",
            )
        except Exception as e:
            logger.error(f"Plivo error: {str(e)}")
            raise gr.Error(str(e))

    def initiate_call(
        self,
        provider: str,
        system_prompt: str,
        country_code: str,
        phone_number: str
    ) -> str:
        """Initiate a single call through the specified provider."""
        formatted_number = PhoneNumberValidator.format_phone_number(
            country_code, phone_number
        )

        gr.Info("Creating Ultravox call...")
        join_url, call_id = self._create_ultravox_call(system_prompt, provider)

        if provider == "Twilio":
            self._initiate_twilio_call(join_url, formatted_number)
        elif provider == "Plivo":
            self._initiate_plivo_call(join_url, formatted_number)
        
        return call_id




class UIComponentBuilder:
    """Builds reusable UI components."""

    @staticmethod
    def create_provider_dropdown(value: str = "Twilio", elem_classes: str = "w-full") -> gr.Dropdown:
        """Create provider dropdown component."""
        return gr.Dropdown(
            choices=["Twilio", "Plivo"],
            label="Provider",
            value=value,
            interactive=True,
            elem_classes=elem_classes,
        )

    @staticmethod
    def create_assistant_dropdown(elem_classes: str = "w-full") -> gr.Dropdown:
        """Create assistant type dropdown component."""
        choices = list(ASSISTANT_TYPES.keys())
        return gr.Dropdown(
            choices=choices,
            label="Call Type",
            value=choices[0],
            interactive=True,
            elem_classes=elem_classes
        )

    @staticmethod
    def create_country_code_dropdown(elem_classes: str = "w-1/3") -> gr.Dropdown:
        """Create country code dropdown component."""
        return gr.Dropdown(
            choices=[f"{c['name']} ({c['code']})" for c in COUNTRY_CODES],
            label="Country Code",
            value=f"{COUNTRY_CODES[0]['name']} ({COUNTRY_CODES[0]['code']})",
            elem_classes=elem_classes,
        )

    @staticmethod
    def create_system_prompt_textarea(
        label: str = "Call Prompt",
        value: str = None,
        elem_classes: str = "w-full border border-gray-300 p-2 rounded-lg"
    ) -> gr.TextArea:
        """Create system prompt textarea component."""
        return gr.TextArea(
            label=label,
            lines=8,
            value=value or ASSISTANT_TYPES["Interview Scheduling"],
            elem_classes=elem_classes
        )


class UltravoxInterface:
    """Main interface class for the Ultravox application."""

    def __init__(self):
        self.call_manager = UltravoxCallManager()
        self.batch_processor = BatchProcessor(self.call_manager)
        self.csv_data: Optional[pd.DataFrame] = None

    def update_prompt(self, selected_type: str) -> str:
        """Update system prompt based on selected assistant type."""
        return ASSISTANT_TYPES[selected_type]

    def process_csv_upload(self, file) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """Process uploaded CSV file."""
        if file is None:
            return None, None

        try:
            self.csv_data = pd.read_csv(
                file.name, dtype={'country_code': str, 'phone_number': str}
            )
            preview_df = self.csv_data.head(3)
            return self.csv_data, preview_df
        except Exception as e:
            logger.error(f"CSV processing error: {str(e)}")
            return None, None


    def create_interface(self) -> gr.Blocks:
        """Create the main Gradio interface."""
        with gr.Blocks(theme="soft") as interface:
            gr.Markdown(
                "# 📞 Ultravox Call Manager",
                elem_classes="text-3xl font-bold text-center"
            )

            with gr.Tabs():
                # Single Call Tab
                with gr.TabItem("Single Call"):
                    with gr.Row():
                        provider_single = UIComponentBuilder.create_provider_dropdown()

                    with gr.Row():
                        assistant_type_single = UIComponentBuilder.create_assistant_dropdown()

                    with gr.Row():
                        country_code_single = UIComponentBuilder.create_country_code_dropdown()
                        phone_number_single = gr.Textbox(
                            label="Mobile Number",
                            placeholder="Enter mobile number without country code",
                            max_lines=1,
                            elem_classes="w-2/3",
                        )

                    system_prompt_single = UIComponentBuilder.create_system_prompt_textarea()

                    with gr.Row():
                        submit_btn_single = gr.Button(
                            "📞 Initiate Call",
                            variant="primary",
                            elem_classes="w-1/2 bg-blue-600 text-white"
                        )
                        clear_btn_single = gr.Button(
                            "🧹 Clear",
                            variant="secondary",
                            elem_classes="w-1/2 bg-gray-400 text-white"
                        )

                # Batch Calls Tab
                with gr.TabItem("Batch Calls (CSV)"):
                    gr.Markdown("### 📋 CSV Column Requirements")
                    gr.Markdown("""
                    - `phone_number` - Phone numbers without country code, Required
                    - `country_code` - Country codes (e.g., +91, +1, +44), Required
                    - Any other columns can be used as `{{column_name}}` in your prompt template
                    """)

                    with gr.Row():
                        csv_file = gr.File(
                            label="Upload CSV File",
                            file_types=[".csv"],
                            elem_classes="w-full"
                        )

                    csv_preview = gr.DataFrame(
                        label="CSV Preview (First 3 rows)",
                        headers=["Column"],
                        datatype=["str"],
                        elem_classes="w-full"
                    )

                    gr.Markdown("### 🔧 Configuration")
                    with gr.Row():
                        provider_batch = UIComponentBuilder.create_provider_dropdown(elem_classes="w-1/2")
                        assistant_type_batch = UIComponentBuilder.create_assistant_dropdown(elem_classes="w-1/2")

                    system_prompt_batch = UIComponentBuilder.create_system_prompt_textarea(
                        label="Call Prompt Template"
                    )

                    csv_columns_state = gr.State([])

                    gr.Markdown("### ⚙️ Processing Settings")
                    with gr.Row():
                        call_delay = gr.Number(
                            label="Delay Between Calls (seconds)",
                            value=5,
                            minimum=2,
                            maximum=60,
                            step=1,
                            elem_classes="w-full"
                        )

                    gr.Markdown("### 🚀 Batch Processing")
                    with gr.Row():
                        start_batch_btn = gr.Button(
                            "🚀 Start Batch Processing",
                            variant="primary",
                            elem_classes="w-1/3"
                        )
                        stop_batch_btn = gr.Button(
                            "🛑 Stop Processing",
                            variant="secondary",
                            elem_classes="w-1/3"
                        )
                        refresh_status_btn = gr.Button(
                            "🔄 Refresh Status",
                            variant="secondary",
                            elem_classes="w-1/3"
                        )

                    batch_status = gr.Textbox(
                        label="Processing Status",
                        value="Ready to start",
                        interactive=False,
                        elem_classes="w-full"
                    )

                    batch_results = gr.JSON(
                        label="Processing Results",
                        value=[],
                        elem_classes="w-full"
                    )

            self._setup_event_handlers(
                # Single call components
                assistant_type_single, system_prompt_single, provider_single,
                country_code_single, phone_number_single, submit_btn_single,
                clear_btn_single,
                # Batch call components
                assistant_type_batch, system_prompt_batch, csv_file,
                csv_columns_state, csv_preview, start_batch_btn,
                provider_batch, call_delay, stop_batch_btn,
                refresh_status_btn, batch_status, batch_results
            )

        return interface

    def _setup_event_handlers(self, *components) -> None:
        """Setup all event handlers for the interface."""
        (
            assistant_type_single, system_prompt_single, provider_single,
            country_code_single, phone_number_single, submit_btn_single,
            clear_btn_single, assistant_type_batch, system_prompt_batch,
            csv_file, csv_columns_state, csv_preview, start_batch_btn,
            provider_batch, call_delay, stop_batch_btn, refresh_status_btn,
            batch_status, batch_results
        ) = components

        def get_country_code(selection: str) -> str:
            return selection.split("(")[1].strip(")")

        # Single call event handlers
        assistant_type_single.change(
            fn=self.update_prompt,
            inputs=[assistant_type_single],
            outputs=[system_prompt_single]
        )

        assistant_type_batch.change(
            fn=self.update_prompt,
            inputs=[assistant_type_batch],
            outputs=[system_prompt_batch]
        )

        submit_btn_single.click(
            fn=lambda prov, p, c, n: (
                call_id := self.call_manager.initiate_call(
                    prov, p, get_country_code(c), n
                ),
                None  # Return None to not affect UI
            )[1],
            inputs=[
                provider_single, system_prompt_single,
                country_code_single, phone_number_single
            ],
            outputs=[],
        )

        clear_btn_single.click(
            fn=lambda: [
                "Twilio",
                f"{COUNTRY_CODES[0]['name']} ({COUNTRY_CODES[0]['code']})",
                "", ""
            ],
            inputs=[],
            outputs=[
                provider_single, country_code_single,
                phone_number_single, system_prompt_single
            ],
        )

        # Batch call event handlers
        csv_file.change(
            fn=self.process_csv_upload,
            inputs=[csv_file],
            outputs=[csv_columns_state, csv_preview]
        )

        start_batch_btn.click(
            fn=self.batch_processor.start_async_processing,
            inputs=[provider_batch, system_prompt_batch, csv_columns_state, call_delay],
            outputs=[batch_status]
        )

        stop_batch_btn.click(
            fn=self.batch_processor.stop_processing,
            outputs=[batch_status]
        )

        refresh_status_btn.click(
            fn=lambda: (
                self.batch_processor.get_status(),
                self.batch_processor.get_results()
            ),
            outputs=[batch_status, batch_results]
        )


def main() -> None:
    """Main application entry point."""
    app = UltravoxInterface()
    interface = app.create_interface()
    interface.launch(share=True, server_name="0.0.0.0")


if __name__ == "__main__":
    main()
