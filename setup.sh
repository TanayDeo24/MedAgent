#!/bin/bash

# MedAgent Setup Script
# This script sets up the complete development environment for MedAgent

set -e  # Exit on error

echo "=============================================="
echo "   MedAgent Setup - Day 1"
echo "=============================================="
echo ""

# Check Python version
echo "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
REQUIRED_VERSION="3.10"

if (( $(echo "$PYTHON_VERSION < $REQUIRED_VERSION" | bc -l) )); then
    echo "❌ Error: Python $REQUIRED_VERSION or higher is required"
    echo "   Current version: $PYTHON_VERSION"
    exit 1
fi
echo "✓ Python $PYTHON_VERSION detected"
echo ""

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Create virtual environment
echo "Creating virtual environment..."
if [ -d "venv" ]; then
    echo "  Virtual environment already exists"
else
    python3 -m venv venv
    echo "✓ Virtual environment created"
fi
echo ""

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate
echo "✓ Virtual environment activated"
echo ""

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip --quiet
echo "✓ pip upgraded"
echo ""

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt --quiet
echo "✓ Dependencies installed"
echo ""

# Create necessary directories
echo "Creating directory structure..."
mkdir -p logs
mkdir -p data
echo "✓ Directories created"
echo ""

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "✓ .env file created (please edit with your API keys)"
else
    echo "  .env file already exists"
fi
echo ""

# Install package in development mode
echo "Installing MedAgent package in development mode..."
pip install -e . --quiet
echo "✓ Package installed"
echo ""

echo "=============================================="
echo "   Setup Complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Activate the virtual environment:"
echo "   $ source venv/bin/activate"
echo ""
echo "2. (Optional) Edit .env file to add API keys:"
echo "   $ nano .env"
echo ""
echo "3. Run examples to test the tools:"
echo "   $ python examples/test_pubmed.py"
echo "   $ python examples/test_clinical_trials.py"
echo "   $ python examples/test_chembl.py"
echo ""
echo "4. Run validation script:"
echo "   $ python validate.py"
echo ""
echo "5. Run tests:"
echo "   $ pytest tests/ -v"
echo ""
echo "For more information, see README.md"
echo ""
