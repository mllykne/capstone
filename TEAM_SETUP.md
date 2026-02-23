# 🚀 Team Setup Guide

## Quick Start for Development Team

### 1. Clone and Setup
```bash
# Navigate to project directory
cd capstone_ai

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows:
.\.venv\Scripts\Activate.ps1
# On macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration
```bash
# Copy the example environment file
copy .env.example .env

# Edit .env file and add your Google Gemini API key:
GEMINI_API_KEY=your_actual_api_key_here
```

### 3. Run the Application
```bash
python app_unified.py
```

Visit **http://localhost:5000** to access the application.

## 📋 Features Available

- **Document Browser**: Browse and classify existing demo documents
- **Upload & Test**: Upload new documents for instant classification  
- **Site Scanner**: Run comprehensive scans across all SharePoint sites
- **Risk Assessment**: Get detailed risk scores and PII detection

## 🔧 Development Notes

- Application runs in production mode by default
- Set `FLASK_DEBUG=1` in `.env` for development mode
- Demo documents are located in `demo_sharepoint/` directory
- All uploads are saved to `uploads/` directory
- Classification results are logged to `logs/app.log`

## 📊 Demo Data

The system includes demo SharePoint sites with sample documents:
- **HR Site**: Employee records, performance reviews
- **Finance Site**: Budgets, financial reports, consulting documents  
- **Legal Site**: Contracts, legal documents
- **IT Site**: Technical specifications, system documents
- And more...

## 🔐 Security

- Never commit `.env` file with real API keys
- The `.env` file is already in `.gitignore`
- Use `.env.example` as template for new team members