# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an Ultravox-powered voice AI call management system built with Gradio. The application enables making voice calls through Twilio/Plivo providers using the Ultravox AI platform for conversational AI agents. It supports both single calls and batch processing from CSV files.

## Development Commands

### Running the Application
```bash
python app.py
```
The app runs on `0.0.0.0:7860` and creates a shareable Gradio interface.

### Installing Dependencies
```bash
pip install -r requirements.txt
```

### Environment Setup
Copy `.env.example` to `.env` and configure:
- `ULTRAVOX_API_KEY` - Ultravox API key for call creation
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` - Twilio integration
- `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN`, `PLIVO_PHONE_NUMBER` - Plivo integration
- `SUPABASE_URL`, `SUPABASE_KEY` - Database for call tracking

## Architecture

### Core Components

**`app.py`** - Main application with Gradio interface
- `UltravoxCallManager` - Handles Ultravox API calls and provider integration
- `BatchProcessor` - Manages CSV-based batch call processing with threading
- `UltravoxInterface` - Main UI class with three tabs: Single Call, Batch Calls, Call Details
- `TemplateProcessor` - Handles `{{variable}}` substitution in prompts

**`supabase_client.py`** - Database operations
- `SupabaseClient` - CRUD operations for call tracking table
- Stores call metadata: call_id, phone_number, status, duration, summary, etc.

**`assistants.py`** - AI agent prompt templates
- Contains predefined system prompts for different use cases (interview scheduling, customer support, real estate, etc.)
- Templates use `{{variable_name}}` format for dynamic content substitution

### Data Flow

1. **Call Creation**: User configures provider, prompt, and phone number → Ultravox API creates call → Returns join URL and call_id
2. **Provider Integration**: Join URL passed to Twilio/Plivo → Provider initiates actual phone call
3. **Call Tracking**: Call metadata stored in Supabase → Status/summary updated via Ultravox API
4. **Batch Processing**: CSV data processed row-by-row → Template variables replaced → Individual calls created

### Key Integrations

- **Ultravox API**: `https://api.ultravox.ai/api/calls` for call creation and details
- **Twilio**: Uses TwiML `<Connect><Stream>` for real-time audio streaming
- **Plivo**: Uses webhook URL for call connection
- **Supabase**: PostgreSQL database for call history and metadata

## Template System

The application uses `{{variable_name}}` syntax for dynamic content:
- Variables extracted via regex: `r'\{\{([^}]+)\}\}'`
- CSV columns automatically mapped to template variables
- Common variables: `{{lead_contact_name}}`, `{{lead_company_name}}`, `{{lead_phone_number}}`

## Call Details Dashboard

- **Real-time API Integration**: Always fetches fresh data from Ultravox API for all calls
- **Comprehensive Display**: Shows call ID, start time, duration, billed duration, agent, and full summary
- **Smart Status Handling**: Handles "Never Joined" calls and API errors gracefully
- **Time Formatting**: Converts ISO timestamps to readable MM/DD/YYYY HH:MM AM/PM format
- **Duration Formatting**: Displays durations in HH:MM:SS format
- **Full Summaries**: No truncation - complete call summaries displayed in table
- **Export Functionality**: CSV export of call history with timestamps

## Database Schema

The `calls` table contains:
- `call_id` (string) - Ultravox call identifier
- `phone_number` (string) - E.164 formatted number
- `status` (string) - Call status/end reason
- `duration` (integer) - Call duration in seconds
- `summary` (text) - AI-generated call summary
- `assistant_type` (string) - Agent type used
- `provider` (string) - Twilio/Plivo
- `created_at` (timestamp) - Call creation time

## Assistant Configuration

Each assistant in `assistants.py` follows this structure:
- **Call Information** - Template variables for personalization
- **Identity** - AI persona and role definition
- **Style** - Communication guidelines and tone
- **Methodology** - Conversation flow and framework
- **Tasks** - Step-by-step conversation script with examples
- **Objection Handling** - Responses to common customer concerns

## Important Notes

- All phone numbers automatically validated and formatted to E.164 standard
- Batch processing runs in separate threads to avoid UI blocking
- Call summaries are fetched asynchronously and stored for future reference
- The system supports up to 300 employees for group calls (SME focus)
- Rate limiting: Configurable delay between batch calls (default 5 seconds)