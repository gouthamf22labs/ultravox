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
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import pytz
from supabase_client import SupabaseClient
from assistants import (
    FITMENT_CHECK_AGENT,

)

load_dotenv(override=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


ASSISTANT_TYPES = {
    "Fitment Check Agent": FITMENT_CHECK_AGENT,
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
        """Process batch calls from CSV data using the selected provider."""
        logger.info(f"Starting batch processing: {len(csv_data)} calls")

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
                
                # Use the provider selected from dropdown
                logger.info(f"Using provider: {provider} for {phone_number}")

                # Extract candidate details if available
                candidate_name = None
                position = None
                company = None

                if 'name' in row.index:
                    candidate_name = str(row['name']) if pd.notna(row['name']) else None
                if 'position' in row.index:
                    position = str(row['position']) if pd.notna(row['position']) else None
                if 'company' in row.index:
                    company = str(row['company']) if pd.notna(row['company']) else None

                # Make the call
                try:
                    # Determine assistant type from the system prompt or use default
                    assistant_type = "Batch Call"
                    call_id = self.call_manager.initiate_call(
                        provider, personalized_prompt, country_code, phone_number, assistant_type, candidate_name, position, company
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
            return "Error: Batch processing already running"

        is_valid, error_msg = self.validate_csv_data(csv_data)
        if not is_valid:
            return f"Error: {error_msg}"

        def run_batch():
            return self.process_batch_calls(provider, system_prompt, csv_data, delay)

        self._thread = threading.Thread(target=run_batch)
        self._thread.start()
        return "Batch processing started! Check the progress below."

    def stop_processing(self) -> str:
        """Stop the batch processing."""
        logger.info("Batch processing stopped by user")
        self.is_processing = False
        return "Batch processing stopped"

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
        try:
            self.supabase_client = SupabaseClient()
        except ValueError as e:
            logger.warning(f"Supabase not configured: {e}")
            self.supabase_client = None

    def _create_ultravox_call(self, system_prompt: str, provider: str) -> str:
        """Create a call via Ultravox API and return join URL with retry logic."""
        call_config = {
            "systemPrompt": system_prompt,
            "model": "fixie-ai/ultravox",
            "voice": "Monika-English-Indian",
            "temperature": 0.3,
            "firstSpeaker": "FIRST_SPEAKER_AGENT",
            "medium": {provider.lower(): {}},
            "recordingEnabled": True,
            "vadSettings": {
            "turnEndpointDelay": "1.00s"
            },
            "selectedTools": [
            {
            "toolName": "hangUp",
            "parameterOverrides": {
                "strict": False
            }
            }
        ]
        }

        max_retries = 5

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(
                    "https://api.ultravox.ai/api/calls",
                    headers={
                        "Content-Type": "application/json",
                        "X-API-Key": self.env_vars["ULTRAVOX_API_KEY"],
                    },
                    json=call_config,
                )

                # Handle concurrency limit errors (429/503)
                if response.status_code in [429, 503]:
                    if attempt < max_retries:
                        retry_after = response.headers.get('Retry-After')
                        if retry_after:
                            try:
                                delay = int(retry_after)
                            except ValueError:
                                # Parse HTTP date format
                                try:
                                    retry_date = parsedate_to_datetime(retry_after)
                                    delay = (retry_date - datetime.now(timezone.utc)).total_seconds()
                                    delay = max(1, int(delay))  # At least 1 second
                                except Exception:
                                    # Fallback to exponential backoff
                                    delay = 2 ** (attempt - 1)
                                    logger.warning(f"Could not parse Retry-After header: {retry_after}")
                        else:
                            # Exponential backoff if no Retry-After header: 1s, 2s, 4s
                            delay = 2 ** (attempt - 1)

                        logger.warning(
                            f"HTTP {response.status_code}: Concurrency limit reached. "
                            f"Attempt {attempt}/{max_retries}. Retrying after {delay}s..."
                        )
                        time.sleep(delay)
                        continue
                    else:
                        logger.error(f"Max retries ({max_retries}) exceeded. HTTP {response.status_code}")
                        raise gr.Error(
                            f"Concurrency limit reached. Failed after {max_retries} attempts. "
                            f"Please try again later."
                        )

                # Check for other HTTP errors
                response.raise_for_status()

                response_data = response.json()
                join_url = response_data.get("joinUrl")
                call_id = response_data.get("callId")

                if attempt > 1:
                    logger.info(f"Call created successfully on attempt {attempt}")

                logger.info(f"Ultravox Call ID: {call_id}")
                print(f"Ultravox Call ID: {call_id}")  # Also print to ensure visibility

                if not join_url:
                    raise gr.Error("Failed to create call")
                return join_url, call_id

            except requests.exceptions.RequestException as e:
                # Log and raise error if not a retry-able error
                if attempt >= max_retries:
                    logger.error(f"Ultravox API error after {attempt} attempts: {str(e)}")
                    raise gr.Error(str(e))
                else:
                    logger.warning(f"Request failed on attempt {attempt}/{max_retries}: {str(e)}")
                    # Will retry on next iteration

        # Fallback error (should not reach here)
        raise gr.Error(f"Failed to create call after {max_retries} attempts")

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
            gr.Info(f"Twilio call initiated! Call SID: {call.sid}")
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

    def fetch_call_details(self, call_id: str) -> Dict[str, Any]:
        """Fetch call details from Ultravox API."""
        try:
            response = requests.get(
                f"https://api.ultravox.ai/api/calls/{call_id}",
                headers={
                    "X-API-Key": self.env_vars["ULTRAVOX_API_KEY"],
                }
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching call details for {call_id}: {str(e)}")
            return {}

    def fetch_calls_page(self, page_size: int = 20, cursor: str = None) -> Dict[str, Any]:
        """Fetch a single page of calls from Ultravox API."""
        try:
            # Build request parameters
            params = {"pageSize": page_size}
            if cursor:
                params["cursor"] = cursor

            logger.info(f"Fetching single page: pageSize={page_size}, cursor={cursor[:20] if cursor else 'None'}")

            response = requests.get(
                "https://api.ultravox.ai/api/calls",
                headers={"X-API-Key": self.env_vars["ULTRAVOX_API_KEY"]},
                params=params,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            results = data.get('results', [])
            total = data.get('total', 0)
            next_cursor = None
            prev_cursor = None

            # Extract cursors from next/previous URLs if they exist
            next_url = data.get('next')
            if next_url:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(next_url)
                query_params = parse_qs(parsed.query)
                next_cursor = query_params.get('cursor', [None])[0]

            prev_url = data.get('previous')
            if prev_url:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(prev_url)
                query_params = parse_qs(parsed.query)
                prev_cursor = query_params.get('cursor', [None])[0]

            logger.info(f"Page fetched: {len(results)} calls, total available: {total}")

            return {
                "results": results,
                "total": total,
                "next_cursor": next_cursor,
                "prev_cursor": prev_cursor,
                "has_next": next_cursor is not None,
                "has_prev": prev_cursor is not None
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching calls page: {str(e)}")
            return {
                "results": [],
                "total": 0,
                "next_cursor": None,
                "prev_cursor": None,
                "has_next": False,
                "has_prev": False
            }

    def fetch_call_transcript(self, call_id: str) -> str:
        """Fetch call transcript from Ultravox API."""
        try:
            response = requests.get(
                f"https://api.ultravox.ai/api/calls/{call_id}/messages",
                headers={
                    "X-API-Key": self.env_vars["ULTRAVOX_API_KEY"],
                }
            )
            response.raise_for_status()
            transcript_data = response.json()
            
            # Format the transcript from the results array
            if 'results' in transcript_data and transcript_data['results']:
                formatted_transcript = []
                for message in transcript_data['results']:
                    role = message.get('role', 'Unknown')
                    text = message.get('text', '')
                    if text.strip():
                        # Skip system-generated phone greeting messages
                        if text.strip() in ["(New Call) Respond as if you are answering the phone.", "Respond as if you are answering the phone."]:
                            continue
                            
                        # Format role name
                        if role == 'MESSAGE_ROLE_AGENT':
                            speaker = 'Agent'
                        elif role == 'MESSAGE_ROLE_USER':
                            speaker = 'User'
                        else:
                            speaker = role.replace('MESSAGE_ROLE_', '').capitalize()
                        
                        formatted_transcript.append(f"{speaker}: {text}")
                
                return "\n\n".join(formatted_transcript) if formatted_transcript else "No transcript available"
            else:
                return "No transcript available"
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching transcript for {call_id}: {str(e)}")
            return "Transcript not available"

    def initiate_call(
        self,
        provider: str,
        system_prompt: str,
        country_code: str,
        phone_number: str,
        assistant_type: str = None,
        candidate_name: str = None,
        position: str = None,
        company: str = None
    ) -> str:
        """Initiate a single call through the specified provider."""
        formatted_number = PhoneNumberValidator.format_phone_number(
            country_code, phone_number
        )

        gr.Info("Creating Ultravox call...")
        join_url, call_id = self._create_ultravox_call(system_prompt, provider)

        # Store call in Supabase
        if self.supabase_client:
            try:
                call_data = {
                    "call_id": call_id,
                    "phone_number": formatted_number,
                    "country_code": country_code,
                    "provider": provider,
                    "assistant_type": assistant_type or "Unknown",
                    "candidate_name": candidate_name,
                    "position": position,
                    "company": company,
                    "status": "initiated",
                    "created_at": datetime.now().isoformat()
                }
                self.supabase_client.insert_call(call_data)
            except Exception as e:
                logger.error(f"Failed to store call in Supabase: {e}")

        if provider == "Twilio":
            self._initiate_twilio_call(join_url, formatted_number)
        elif provider == "Plivo":
            self._initiate_plivo_call(join_url, formatted_number)

        return call_id




class UIComponentBuilder:
    """Builds reusable UI components."""

    @staticmethod
    def create_provider_dropdown(value: str = "Plivo", elem_classes: str = "w-full") -> gr.Dropdown:
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
        # Use the first item in ASSISTANT_TYPES (same as dropdown default)
        default_prompt = list(ASSISTANT_TYPES.values())[0]
        return gr.TextArea(
            label=label,
            lines=8,
            value=value or default_prompt,
            elem_classes=elem_classes
        )


class UltravoxInterface:
    """Main interface class for the Ultravox application."""

    def __init__(self):
        self.call_manager = UltravoxCallManager()
        self.batch_processor = BatchProcessor(self.call_manager)
        self.csv_data: Optional[pd.DataFrame] = None
        self.calls_per_page = 20  # Match API page size
        self.current_page = 1
        self.total_calls = 0
        self.current_cursor = None
        self.next_cursor = None
        self.prev_cursor = None
        self.page_cursors = {}  # Track cursors for each page

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

    def replace_qg_in_prompt(self, prompt: str, qg_data: Dict[str, str]) -> str:
        """Replace Q&G placeholders in the prompt with dynamically built screening questions (max 5)."""
        result = prompt
        
        # Build the screening questions section dynamically
        screening_questions = []
        
        # Get all Q numbers (sorted)
        q_numbers = sorted([int(key[1:]) for key in qg_data.keys() if key.startswith('Q')])
        
        # Limit to max 5 questions
        q_numbers = q_numbers[:5]
        
        for q_num in q_numbers:
            q_key = f"Q{q_num}"
            g_key = f"G{q_num}"
            
            if q_key in qg_data and qg_data[q_key]:
                q_text = qg_data[q_key]
                g_text = qg_data.get(g_key, "")
                
                # Build Q&G block
                qg_block = f"{q_key}: {q_text}\n{g_key}:\n{g_text}\n< wait for user response >\n"
                screening_questions.append(qg_block)
        
        # Join all screening questions
        screening_questions_text = "\n".join(screening_questions) if screening_questions else ""
        
        # Replace the {{SCREENING_QUESTIONS}} placeholder
        result = result.replace("{{SCREENING_QUESTIONS}}", screening_questions_text)
        
        # Also support individual Q&G replacement for backward compatibility
        for key, value in qg_data.items():
            placeholder = f"{{{{{key}}}}}"
            result = result.replace(placeholder, value)
        
        return result

    def build_qg_dict(self, visibility, *values) -> Dict[str, str]:
        """Build a dictionary from Q&G input values, only including visible pairs."""
        qg_dict = {}
        for i in range(0, len(values), 2):
            if i + 1 < len(values):
                pair_index = i // 2  # 0-based index
                # Only process if this Q&G pair is visible
                if pair_index < len(visibility) and visibility[pair_index]:
                    q_num = pair_index + 1
                    q_value = values[i] if values[i] else ""
                    g_value = values[i+1] if values[i+1] else ""
                    if q_value:  # Only add if question has value
                        qg_dict[f"Q{q_num}"] = q_value
                        qg_dict[f"G{q_num}"] = g_value
        return qg_dict

    def refresh_call_details(self, direction: str = "refresh") -> Tuple[pd.DataFrame, str]:
        """Refresh call details using cursor-based pagination from Ultravox API."""
        try:
            # Determine which cursor to use based on direction
            if direction == "refresh":
                cursor = None  # Start from beginning
                self.current_page = 1
                self.page_cursors = {}
            elif direction == "next":
                cursor = self.next_cursor
                self.current_page += 1
            elif direction == "prev":
                cursor = self.prev_cursor
                self.current_page -= 1
            else:
                cursor = self.current_cursor

            # Fetch current page from Ultravox API
            page_data = self.call_manager.fetch_calls_page(page_size=self.calls_per_page, cursor=cursor)
            ultravox_calls = page_data.get('results', [])
            self.total_calls = page_data.get('total', 0)

            # Update cursor tracking
            self.current_cursor = cursor
            self.next_cursor = page_data.get('next_cursor')
            self.prev_cursor = page_data.get('prev_cursor')
            self.page_cursors[self.current_page] = cursor

            # Build dashboard data from current page
            dashboard_data = []

            for ultravox_call in ultravox_calls:
                call_id = ultravox_call.get('callId')
                if not call_id:
                    continue

                # Extract data from Ultravox API response
                created = ultravox_call.get('created', '')
                end_reason = ultravox_call.get('endReason', '')
                billed_duration = ultravox_call.get('billedDuration', '')
                summary = ultravox_call.get('summary', '')
                short_summary = ultravox_call.get('shortSummary', '')

                # Try to get additional details from Supabase if available
                phone_number = ""
                candidate_name = ""
                position = ""
                company = ""

                if self.call_manager.supabase_client:
                    try:
                        supabase_call = self.call_manager.supabase_client.get_call_by_id(call_id)
                        if supabase_call:
                            phone_number = supabase_call.get('phone_number', '')
                            candidate_name = supabase_call.get('candidate_name', '') or ''
                            position = supabase_call.get('position', '') or ''
                            company = supabase_call.get('company', '') or ''
                    except Exception as e:
                        logger.warning(f"Could not fetch Supabase data for {call_id}: {e}")

                # Format the created timestamp
                formatted_created = self.format_datetime(created)

                # Generate clickable markdown link for Call ID
                call_id_link = f"[{call_id}](https://app.ultravox.ai/calls/{call_id})"

                # Create View button for summary if summary exists
                summary_display = ""
                if summary and summary.strip():
                    # Escape special characters for JavaScript
                    escaped_summary = summary.replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
                    summary_display = f'<button onclick="showSummary(\'{call_id}\', \'{escaped_summary}\')" style="background-color: #3b82f6; color: white; padding: 4px 8px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px;">View</button>'
                else:
                    summary_display = "No summary"

                # Create View button for transcript
                transcript_display = ""
                if end_reason not in ["Not Found", ""]:
                    # Fetch transcript for this call
                    transcript = self.call_manager.fetch_call_transcript(call_id)
                    if transcript and transcript.strip() and transcript not in ["No transcript available", "Transcript not available"]:
                        # Escape special characters for JavaScript
                        escaped_transcript = transcript.replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
                        transcript_display = f'<button onclick="showTranscript(\'{call_id}\', \'{escaped_transcript}\')" style="background-color: #10b981; color: white; padding: 4px 8px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px;">View</button>'
                    else:
                        transcript_display = "No transcript"
                else:
                    transcript_display = "Not available"

                # Add row to dashboard data
                dashboard_data.append([
                    call_id_link,
                    candidate_name,
                    position,
                    company,
                    phone_number,
                    formatted_created,
                    end_reason or "",
                    billed_duration or "",
                    summary_display,
                    transcript_display,
                    short_summary or ""
                ])

            # Create DataFrame
            df = pd.DataFrame(dashboard_data, columns=[
                "CALL ID", "CANDIDATE NAME", "POSITION", "COMPANY", "PHONE NUMBER", "CREATED", "END REASON", "DURATION", "SUMMARY", "TRANSCRIPT", "SHORT SUMMARY"
            ])

            # Calculate pagination info
            total_pages = (self.total_calls + self.calls_per_page - 1) // self.calls_per_page
            if total_pages == 0:
                total_pages = 1

            pagination_info = f"Page {self.current_page} of {total_pages} ( Total available calls : {self.total_calls})"

            logger.info(f"Displayed page {self.current_page}: {len(df)} calls")
            return df, pagination_info

        except Exception as e:
            logger.error(f"Error refreshing call details: {e}")
            gr.Error(f"Error refreshing calls: {str(e)}")
            return pd.DataFrame(), "Page 0 of 0 ( Total available calls : 0)"

    def go_to_previous_page(self) -> Tuple[pd.DataFrame, str]:
        """Go to the previous page."""
        if self.prev_cursor is not None:
            return self.refresh_call_details("prev")
        return self.refresh_call_details("refresh")

    def go_to_next_page(self) -> Tuple[pd.DataFrame, str]:
        """Go to the next page."""
        if self.next_cursor is not None:
            return self.refresh_call_details("next")
        return self.refresh_call_details("refresh")

    def export_calls_to_csv(self) -> Tuple[str, str]:
        """Export all calls data to CSV file for download."""
        if not self.call_manager.supabase_client:
            return "Warning: Supabase not configured - cannot export data", None

        try:
            # Get all calls from Supabase
            calls = self.call_manager.supabase_client.get_all_calls()

            if not calls:
                return "Warning: No calls found to export", None

            # For CSV export, we need to fetch all calls, so use the old bulk method
            # TODO: Implement proper bulk export with pagination
            ultravox_bulk_data = {"results": [], "total": 0}

            # Temporarily fetch multiple pages for export
            all_calls = []
            cursor = None
            max_export_pages = 100  # Limit export to reasonable size
            page_count = 0

            while cursor is not None or page_count == 0:
                page_data = self.call_manager.fetch_calls_page(page_size=50, cursor=cursor)
                page_results = page_data.get('results', [])
                all_calls.extend(page_results)
                cursor = page_data.get('next_cursor')
                page_count += 1

                if page_count >= max_export_pages or not cursor:
                    break

            ultravox_bulk_data = {"results": all_calls, "total": len(all_calls)}
            ultravox_calls = ultravox_bulk_data.get('results', [])
            
            # Create a lookup dict for faster access
            ultravox_lookup = {call.get('callId'): call for call in ultravox_calls}

            export_data = []

            for call in calls:
                call_id = call.get('call_id')
                phone_number = call.get('phone_number', '')
                candidate_name = call.get('candidate_name', '') or ''
                position = call.get('position', '') or ''
                company = call.get('company', '') or ''
                assistant_type = call.get('assistant_type', '') or ''
                provider = call.get('provider', '') or ''
                
                if not call_id:
                    continue

                # Get details from bulk data lookup
                ultravox_details = ultravox_lookup.get(call_id)

                if ultravox_details:
                    # Extract the essential fields
                    created = ultravox_details.get('created', '')
                    end_reason = ultravox_details.get('endReason', '')
                    billed_duration = ultravox_details.get('billedDuration', '')
                    summary = ultravox_details.get('summary', '')
                    short_summary = ultravox_details.get('shortSummary', '')

                    # Format the created timestamp for CSV
                    formatted_created = self.format_datetime(created)
                    
                    # Fetch transcript for export
                    transcript = self.call_manager.fetch_call_transcript(call_id)
                    if transcript in ["No transcript available", "Transcript not available"]:
                        transcript = ""

                else:
                    # Handle case where call not found in bulk data
                    formatted_created = self.format_datetime(call.get('created_at', ''))
                    end_reason = "Not Found"
                    billed_duration = ""
                    short_summary = "Call not found in Ultravox API"
                    summary = "Call not found in Ultravox API"
                    transcript = ""

                # Add row to export data
                export_data.append({
                    "Call ID": call_id,
                    "Candidate Name": candidate_name,
                    "Position": position,
                    "Company": company,
                    "Phone Number": phone_number,
                    "Created": formatted_created,
                    "End Reason": end_reason,
                    "Duration": billed_duration,
                    "Assistant Type": assistant_type,
                    "Provider": provider,
                    "Summary": summary,
                    "Short Summary": short_summary,
                    "Transcript": transcript
                })

            # Create DataFrame and export to CSV
            import pandas as pd
            from datetime import datetime
            import tempfile
            import os
            
            df = pd.DataFrame(export_data)
            
            # Sort by creation time (most recent first)
            df = df.sort_values('Created', ascending=False)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ultravox_calls_export_{timestamp}.csv"
            
            # Save to temporary file
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, filename)
            df.to_csv(file_path, index=False, encoding='utf-8')
            
            return f"Successfully exported {len(df)} calls", file_path

        except Exception as e:
            logger.error(f"Error exporting calls to CSV: {e}")
            return f"Error exporting calls: {str(e)}", None


    def format_datetime(self, iso_string: str) -> str:
        """Format ISO datetime string to IST readable format."""
        if not iso_string:
            return ""
        try:
            # Parse the UTC datetime
            dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))

            # Convert to IST (UTC+5:30)
            ist = pytz.timezone('Asia/Kolkata')
            dt_ist = dt.astimezone(ist)

            return dt_ist.strftime('%m/%d/%Y %I:%M%p IST')
        except Exception:
            return iso_string


    def create_interface(self) -> gr.Blocks:
        """Create the main Gradio interface."""
        with gr.Blocks(title="Fitment Check", theme="soft", css="""
        footer {display: none !important;}
        .gradio-container {min-height: 0px !important;}
         label span {
            background-color: #ede9fe !important;
            color: #8437bb !important;
            padding: 4px 8px;
            border-radius: 4px;
            display: inline-block;
        }
        label[data-testid="block-label"], .svelte-i3tvor {
            background-color: #ede9fe !important;
            color: #8437bb !important;
            padding: 4px 8px;
            border-radius: 4px;
            display: inline-block;
        }
        .wrap.svelte-12ioyct, .wrap.svelte-12ioyct .or {
            color: #8437bb !important;
        }
        .wrap.svelte-12ioyct svg {
            stroke: #8437bb !important;
        }
        button[role="tab"]{
            background-color: #f9fafb !important;
            color: #8437bb !important;
        }
        button[role="tab"].selected, .svelte-1tcem6n.selected {
            background-color: #ede9fe !important;
            color: #8437bb !important;
        }
        button[role="tab"]::after, button[role="tab"].selected::after {
            display: none !important;
            background: none !important;
        }
        p.svelte-1pch949 {
            color: #000000 !important;
        }
        span[data-testid="block-info"], .svelte-1gfkn6j {
            background-color: rgb(237, 233, 254) !important;
            color: rgb(132, 55, 187) !important;
            padding: 4px 8px;
            border-radius: 4px;
            display: inline-block;
        }
        .primary, button.primary, .gradio-button.primary {
            background-color: #8437bb !important;
            color: white !important;
            border: none !important;
        }
        .primary:hover, button.primary:hover, .gradio-button.primary:hover {
            background-color: #6b2d99 !important;
            color: white !important;
        }
        """, head="""
        <script>
        function showSummary(callId, summary) {
            showModal('Call Summary', callId, summary);
        }
        
        function showTranscript(callId, transcript) {
            showModal('Call Transcript', callId, transcript);
        }
        
        function showModal(type, callId, content) {
            // Create modal overlay
            const overlay = document.createElement('div');
            overlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0, 0, 0, 0.5);
                z-index: 1000;
                display: flex;
                justify-content: center;
                align-items: center;
            `;
            
            // Create modal content
            const modal = document.createElement('div');
            modal.style.cssText = `
                background: white;
                padding: 20px;
                border-radius: 10px;
                max-width: 80%;
                max-height: 80%;
                overflow-y: auto;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                position: relative;
            `;
            
            // Create close button
            const closeBtn = document.createElement('button');
            closeBtn.innerHTML = '×';
            closeBtn.style.cssText = `
                position: absolute;
                top: 10px;
                right: 15px;
                background: none;
                border: none;
                font-size: 24px;
                cursor: pointer;
                color: #666;
            `;
            closeBtn.onclick = () => document.body.removeChild(overlay);
            
            // Create title
            const title = document.createElement('h3');
            title.textContent = type + ' - ' + callId;
            title.style.cssText = 'margin-top: 0; margin-bottom: 15px; color: #333;';
            
            // Create content
            const contentDiv = document.createElement('div');
            contentDiv.textContent = content;
            contentDiv.style.cssText = `
                white-space: pre-wrap;
                line-height: 1.5;
                color: #555;
                height: 400px;
                overflow-y: scroll;
                padding: 10px;
                background-color: #f9f9f9;
                border-radius: 5px;
                border: 1px solid #e0e0e0;
            `;
            
            // Assemble modal
            modal.appendChild(closeBtn);
            modal.appendChild(title);
            modal.appendChild(contentDiv);
            overlay.appendChild(modal);
            
            // Add to document
            document.body.appendChild(overlay);
            
            // Close on overlay click
            overlay.onclick = (e) => {
                if (e.target === overlay) {
                    document.body.removeChild(overlay);
                }
            };
        }
        </script>
        """) as interface:
            gr.Markdown(
                "# Fitment Check Hirevox",
                elem_classes="text-3xl font-bold text-center"
            )

            with gr.Tabs():
                # Calls Tab
                with gr.TabItem("Calls (CSV)"):
                    gr.Markdown("### CSV Column Requirements")
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

                    # Provider selection
                    with gr.Row():
                        provider_dropdown = gr.Dropdown(
                            choices=["Plivo", "Twilio"],
                            label="Provider",
                            value="Plivo",
                            interactive=True,
                            elem_classes="w-full"
                        )

                    # Hidden states - always use Fitment Check Agent
                    assistant_type_batch = gr.State("Fitment Check Agent")
                    system_prompt_batch = gr.State(FITMENT_CHECK_AGENT)

                    # Q&G Section for Batch
                    gr.Markdown("### Q&G Pairs - Questions to Ask")
                    
                    with gr.Accordion("Q&G Pairs", open=True):
                        qg_inputs_batch = []
                        qg_rows_batch = []
                        qg_remove_btns_batch = []
                        
                        for i in range(1, 11):  # Support up to 10 Q&G pairs
                            with gr.Row(visible=False) as row:  # All rows initially hidden
                                with gr.Column(scale=1):
                                    q = gr.TextArea(
                                        label=f"Q{i}",
                                        placeholder=f"Enter question {i}...",
                                        lines=2,
                                        value="",
                                        elem_classes="w-full"
                                    )
                                with gr.Column(scale=1):
                                    g = gr.TextArea(
                                        label=f"G{i}",
                                        placeholder=f"Enter guideline {i}...",
                                        lines=2,
                                        value="",
                                        elem_classes="w-full"
                                    )
                                with gr.Column(scale=0, min_width=60):
                                    remove_btn = gr.Button(
                                        "Remove",
                                        size="sm",
                                        variant="secondary",
                                        elem_classes="mt-6"
                                    )
                                    qg_remove_btns_batch.append((i, remove_btn))
                            qg_inputs_batch.extend([q, g])
                            qg_rows_batch.append(row)
                        
                        add_qg_btn_batch = gr.Button(
                            "Add Q&G Pair",
                            variant="secondary",
                            elem_classes="w-full"
                        )
                    
                    qg_count_batch = gr.State(0)  # Track number of visible Q&G pairs
                    qg_visibility_batch = gr.State([False] * 10)  # Track which rows are visible (10 pairs)

                    csv_columns_state = gr.State([])

                    gr.Markdown("### Processing Settings")
                    with gr.Row():
                        call_delay = gr.Number(
                            label="Delay Between Calls (seconds)",
                            value=5,
                            minimum=2,
                            maximum=60,
                            step=1,
                            elem_classes="w-full"
                        )

                    gr.Markdown("### Batch Processing")
                    with gr.Row():
                        start_batch_btn = gr.Button(
                            "Start Batch Processing",
                            variant="primary",
                            elem_classes="w-1/3"
                        )
                        stop_batch_btn = gr.Button(
                            "Stop Processing",
                            variant="secondary",
                            elem_classes="w-1/3"
                        )
                        refresh_status_btn = gr.Button(
                            "Refresh Status",
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

                # Call Details Tab
                with gr.TabItem("Call History"):
                    gr.Markdown("### Call History")

                    with gr.Row():
                        refresh_calls_btn = gr.Button(
                            "Refresh Call History",
                            variant="primary",
                            elem_classes="w-1/2"
                        )
                        export_csv_btn = gr.Button(
                            "Export to CSV",
                            variant="secondary",
                            elem_classes="w-1/2"
                        )
                    
                    export_status = gr.Textbox(
                        label="Export Status",
                        value="",
                        visible=False,
                        interactive=False,
                        elem_classes="w-full"
                    )
                    
                    download_file = gr.File(
                        label="Download CSV",
                        visible=False,
                        elem_classes="w-full"
                    )

                    calls_table = gr.DataFrame(
                        label="Call History Dashboard",
                        headers=["CALL ID", "CANDIDATE NAME", "POSITION", "COMPANY", "PHONE NUMBER", "CREATED", "END REASON", "DURATION", "SUMMARY", "TRANSCRIPT", "SHORT SUMMARY"],
                        datatype=["markdown", "str", "str", "str", "str", "str", "str", "str", "html", "html", "str"],
                        elem_classes="w-full",
                        column_widths=[200, 120, 120, 120, 120, 130, 120, 80, 100, 100, 250],
                        max_height=600,
                        wrap=True
                    )

                    # Pagination controls at bottom
                    with gr.Row():
                        prev_btn = gr.Button(
                            "Previous",
                            variant="secondary",
                            elem_classes="w-1/4"
                        )
                        pagination_info = gr.Textbox(
                            label="",
                            value="Click Refresh call details to fetch call logs",
                            interactive=False,
                            elem_classes="w-1/2 text-center"
                        )
                        next_btn = gr.Button(
                            "Next",
                            variant="secondary",
                            elem_classes="w-1/4"
                        )

            self._setup_event_handlers(
                # Batch call components
                system_prompt_batch, assistant_type_batch, csv_file,
                csv_columns_state, csv_preview, provider_dropdown, start_batch_btn,
                call_delay, stop_batch_btn,
                refresh_status_btn, batch_status, batch_results, qg_inputs_batch, qg_count_batch, 
                qg_rows_batch, qg_visibility_batch, add_qg_btn_batch, qg_remove_btns_batch,
                # Call Details components
                refresh_calls_btn, export_csv_btn, export_status, download_file, calls_table, prev_btn, next_btn, pagination_info,
            )

        return interface

    def _setup_event_handlers(self, *components) -> None:
        """Setup all event handlers for the interface."""
        (
            system_prompt_batch, assistant_type_batch,
            csv_file, csv_columns_state, csv_preview, provider_dropdown, start_batch_btn,
            call_delay, stop_batch_btn, refresh_status_btn,
            batch_status, batch_results, qg_inputs_batch, qg_count_batch, qg_rows_batch, qg_visibility_batch,
            add_qg_btn_batch, qg_remove_btns_batch,
            refresh_calls_btn, export_csv_btn,
            export_status, download_file, calls_table, prev_btn, next_btn, pagination_info,
        ) = components

        def get_country_code(selection: str) -> str:
            return selection.split("(")[1].strip(")")

        # Q&G Add/Remove button handlers
        def add_more_qg_batch(visibility):
            """Show next Q&G pair for batch call tab (max 5)."""
            # Check if already at max (5 questions)
            if sum(visibility) >= 5:
                gr.Warning("Maximum 5 questions allowed")
                updates = [visibility]
                for i, visible in enumerate(visibility):
                    updates.append(gr.update(visible=visible))
                return [sum(visibility)] + updates
            
            # Find first False (hidden row) and set it to True
            new_visibility = visibility.copy()
            for i in range(len(new_visibility)):
                if not new_visibility[i]:
                    new_visibility[i] = True
                    break
            
            # Update row visibility
            updates = [new_visibility]
            for i, visible in enumerate(new_visibility):
                updates.append(gr.update(visible=visible))
            
            # Calculate count for display
            count = sum(new_visibility)
            return [count] + updates

        def create_remove_handler_batch(row_index):
            """Create remove handler for a specific Q&G pair in batch tab."""
            def remove_qg(visibility, *qg_values):
                # Hide the specified row (row_index is 1-based, so subtract 1)
                new_visibility = visibility.copy()
                new_visibility[row_index - 1] = False
                
                # Clear the Q and G values for this row
                qg_values_list = list(qg_values)
                q_idx = (row_index - 1) * 2
                g_idx = q_idx + 1
                if q_idx < len(qg_values_list):
                    qg_values_list[q_idx] = ""  # Clear Q
                if g_idx < len(qg_values_list):
                    qg_values_list[g_idx] = ""  # Clear G
                
                # Update row visibility
                updates = [new_visibility]
                for i, visible in enumerate(new_visibility):
                    updates.append(gr.update(visible=visible))
                # Update Q and G values
                for val in qg_values_list:
                    updates.append(val)
                
                # Calculate count for display
                count = sum(new_visibility)
                return [count] + updates
            return remove_qg

        add_qg_btn_batch.click(
            fn=add_more_qg_batch,
            inputs=[qg_visibility_batch],
            outputs=[qg_count_batch, qg_visibility_batch] + qg_rows_batch
        )

        # Setup remove button handlers for batch tab
        for row_idx, remove_btn in qg_remove_btns_batch:
            remove_btn.click(
                fn=create_remove_handler_batch(row_idx),
                inputs=[qg_visibility_batch] + qg_inputs_batch,
                outputs=[qg_count_batch, qg_visibility_batch] + qg_rows_batch + qg_inputs_batch
            )

        # Batch call event handlers
        csv_file.change(
            fn=self.process_csv_upload,
            inputs=[csv_file],
            outputs=[csv_columns_state, csv_preview]
        )

        def start_batch_with_qg(prompt, csv_data, delay, provider, visibility, *qg_values):
            """Start batch with Q&G replacements (only visible questions, max 5).
            Uses the selected provider for all calls in the batch."""
            qg_dict = self.build_qg_dict(visibility, *qg_values)
            
            # Log Q&G replacements for batch
            if qg_dict:
                logger.info("=" * 80)
                logger.info("BATCH PROCESSING - Q&G REPLACEMENTS:")
                for key, value in sorted(qg_dict.items()):
                    logger.info(f"  {key}: {value[:100]}..." if len(value) > 100 else f"  {key}: {value}")
                logger.info("=" * 80)
            
            final_prompt = self.replace_qg_in_prompt(prompt, qg_dict)
            
            # Log final batch prompt
            logger.info("=" * 80)
            logger.info(f"BATCH CALL PROMPT (Provider: {provider}, after Q&G replacements):")
            logger.info("-" * 80)
            logger.info(final_prompt)
            logger.info("=" * 80)
            
            # Use the selected provider for all calls
            return self.batch_processor.start_async_processing(provider, final_prompt, csv_data, delay)

        start_batch_btn.click(
            fn=start_batch_with_qg,
            inputs=[system_prompt_batch, csv_columns_state, call_delay, provider_dropdown, qg_visibility_batch] + qg_inputs_batch,
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

        # Call Details event handlers
        refresh_calls_btn.click(
            fn=self.refresh_call_details,
            outputs=[calls_table, pagination_info]
        )

        # Export CSV event handler with loading state
        def show_export_loading():
            return (
                "Exporting calls data... Please wait",
                gr.update(visible=True),
                gr.update(visible=False)
            )
        
        def handle_export():
            status, file_path = self.export_calls_to_csv()
            if file_path:
                return (
                    status,
                    gr.update(visible=True),
                    gr.update(value=file_path, visible=True)
                )
            else:
                return (
                    status,
                    gr.update(visible=True),
                    gr.update(visible=False)
                )

        export_csv_btn.click(
            fn=show_export_loading,
            outputs=[export_status, export_status, download_file]
        ).then(
            fn=handle_export,
            outputs=[export_status, export_status, download_file]
        )

        # Pagination event handlers
        prev_btn.click(
            fn=self.go_to_previous_page,
            outputs=[calls_table, pagination_info]
        )

        next_btn.click(
            fn=self.go_to_next_page,
            outputs=[calls_table, pagination_info]
        )



def main() -> None:
    """Main application entry point."""
    app = UltravoxInterface()
    interface = app.create_interface()
    interface.launch(share=True, server_name="0.0.0.0", show_api=False)


if __name__ == "__main__":
    main()