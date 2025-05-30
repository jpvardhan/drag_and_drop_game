import os
import json
import uuid
import random
from flask import Flask, request, render_template, jsonify
from docx import Document
from werkzeug.utils import secure_filename
import requests # For making HTTP requests to Gemini API

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload size

# Create the uploads folder if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

ALLOWED_EXTENSIONS = {'docx'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_uuid():
    """Generates a unique UUID."""
    return str(uuid.uuid4())

def call_gemini_api(prompt, response_schema=None):
    """
    Makes a call to the Gemini API for text generation or structured data.
    """
    api_key = "AIzaSyBSpvtj1KLxUwzY9s_4MwfixO_PL4o52Ss"
    api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}]
    }

    if response_schema:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
            "responseSchema": response_schema
        }
    
    app.logger.info(f"Sending prompt to Gemini: {prompt[:200]}...") # Log first 200 chars of prompt
    if response_schema:
        app.logger.info(f"With schema: {json.dumps(response_schema)}")

    try:
        response = requests.post(f"{api_url}?key={api_key}", headers=headers, json=payload)
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        result = response.json()
        app.logger.info(f"Gemini API raw response: {json.dumps(result, indent=2)}")

        if result.get("candidates") and result["candidates"][0].get("content") and \
           result["candidates"][0]["content"].get("parts") and \
           result["candidates"][0]["content"]["parts"][0].get("text"):
            
            if response_schema:
                # For structured responses, parse the JSON string
                try:
                    parsed_json = json.loads(result["candidates"][0]["content"]["parts"][0]["text"])
                    app.logger.info(f"Gemini API parsed JSON: {parsed_json}")
                    return parsed_json
                except json.JSONDecodeError as e:
                    app.logger.error(f"Error decoding Gemini API JSON response: {e}. Raw text: {result['candidates'][0]['content']['parts'][0]['text']}")
                    return None
            else:
                # For plain text responses
                app.logger.info(f"Gemini API plain text: {result['candidates'][0]['content']['parts'][0]['text']}")
                return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            app.logger.error(f"Gemini API response missing expected content structure: {result}")
            return None
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error calling Gemini API: {e}")
        return None
    except Exception as e: # Catch any other unexpected errors
        app.logger.error(f"An unexpected error occurred in call_gemini_api: {e}")
        return None


def parse_docx_for_raw_text(file_path):
    """
    Parses a DOCX file to extract all text content.
    """
    full_text = []
    try:
        document = Document(file_path)
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if text:
                full_text.append(text)
    except Exception as e:
        app.logger.error(f"Error parsing document {file_path}: {e}")
        return ""
    return "\n".join(full_text)

def get_structured_game_data_from_ai(document_content):
    """
    Uses Gemini AI to extract and structure game components and use cases from raw document content.
    """
    prompt = (
        f"From the following document content, identify distinct 'components' and their corresponding 'use_cases'. "
        f"The components are typically names of services or tools, and the use cases describe their primary function. "
        f"Extract these as pairs. Ensure each component is unique. "
        f"Format the output strictly as a JSON array of objects, where each object MUST have two keys: 'component' (string) and 'use_case' (string).\n\n"
        f"Document Content:\n{document_content}"
    )

    response_schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "component": {"type": "STRING"},
                "use_case": {"type": "STRING"}
            },
            "required": ["component", "use_case"], # Ensure these keys are present
            "propertyOrdering": ["component", "use_case"]
        }
    }
    
    structured_data = call_gemini_api(prompt, response_schema=response_schema)
    
    # Validate structured_data and ensure it's a list of dicts with required keys
    if not isinstance(structured_data, list) or \
       not all(isinstance(item, dict) and 'component' in item and 'use_case' in item for item in structured_data):
        app.logger.warning("AI failed to provide valid structured game data or missing keys. Using default hardcoded data.")
        return [
            {"component": "CloudWatch Logs", "use_case": "Centralized storage and monitoring of log data from AWS resources, applications, and custom logs."},
            {"component": "Kinesis Data Streams", "use_case": "Real-time collection and processing of high-volume log data for streaming analytics."},
            {"component": "Amazon S3", "use_case": "Long-term archival and storage of log files for compliance and historical analysis."},
            {"component": "CloudWatch Logs Insights", "use_case": "Query and analyze log data interactively to troubleshoot issues and gain insights."},
            {"component": "AWS Lambda", "use_case": "Process and transform log data automatically before routing to storage or analytics services."},
            {"component": "Amazon OpenSearch Service", "use_case": "Search, visualize, and analyze large volumes of log data for operational intelligence."}
        ]
    
    # Ensure uniqueness after AI extraction
    seen_components = set()
    unique_game_data = []
    for item in structured_data:
        if item["component"] not in seen_components:
            unique_game_data.append(item)
            seen_components.add(item["component"])
    
    if not unique_game_data: # If AI returned empty or only duplicates
        app.logger.warning("AI extracted no unique game data. Using default hardcoded data.")
        return [
            {"component": "CloudWatch Logs", "use_case": "Centralized storage and monitoring of log data from AWS resources, applications, and custom logs."},
            {"component": "Kinesis Data Streams", "use_case": "Real-time collection and processing of high-volume log data for streaming analytics."},
            {"component": "Amazon S3", "use_case": "Long-term archival and storage of log files for compliance and historical analysis."},
            {"component": "CloudWatch Logs Insights", "use_case": "Query and analyze log data interactively to troubleshoot issues and gain insights."},
            {"component": "AWS Lambda", "use_case": "Process and transform log data automatically before routing to storage or analytics services."},
            {"component": "Amazon OpenSearch Service", "use_case": "Search, visualize, and analyze large volumes of log data for operational intelligence."}
        ]

    return unique_game_data


def generate_game_json(game_data):
    """
    Generates the JSON structure for the drag-and-drop game based on provided structured game_data.
    """
    cells = []
    component_ids = {}
    use_case_ids = {}
    embeds_list = []

    # Predefined list of colors for components
    colors = ["#FF6347", "#32CD32", "#4169E1", "#FFD700", "#DA70D6", "#00CED1", "#8A2BE2", "#5F9EA0"]
    random.shuffle(colors)

    start_x_component = 550
    start_y_component = 102
    start_x_use_case = 1160
    start_y_use_case = 104
    y_offset = 190

    for i, item in enumerate(game_data):
        comp_id = generate_uuid()
        component_ids[item["component"]] = comp_id
        embeds_list.append(comp_id)
        cells.append({
            "type": "standard.Rectangle",
            "position": {"x": start_x_component, "y": start_y_component + i * y_offset},
            "size": {"width": 393, "height": 133},
            "angle": 0,
            "id": comp_id,
            "data": {"group": "Unified Group"},
            "attrs": {
                "body": {"fill": colors[i % len(colors)], "fillOpacity": 0.5},
                "label": {"fontSize": 30, "fill": "#000000", "textWrap": {"width": -10, "ellipsis": True, "height": "auto"}, "text": item["component"]}
            }
        })

        uc_id = generate_uuid()
        use_case_ids[item["use_case"]] = uc_id
        embeds_list.append(uc_id)
        cells.append({
            "type": "standard.Rectangle",
            "position": {"x": start_x_use_case, "y": start_y_use_case + i * y_offset},
            "size": {"width": 1465, "height": 134},
            "angle": 0,
            "id": uc_id,
            "data": {"group": "Unified Group"},
            "attrs": {
                "body": {"fillOpacity": 0.5},
                "label": {"fontSize": 30, "fill": "#000000", "textWrap": {"width": "1200", "ellipsis": True, "height": "auto"}, "text": item["use_case"]}
            }
        })

    for item in game_data:
        if item["component"] in component_ids and item["use_case"] in use_case_ids:
            cells.append({
                "type": "standard.Link",
                "source": {"id": component_ids[item["component"]]},
                "target": {"id": use_case_ids[item["use_case"]]},
                "id": generate_uuid(),
                "attrs": {}
            })
        else:
            app.logger.warning(f"Skipping link for {item['component']} - {item['use_case']} due to missing ID.")

    main_group_id = generate_uuid()
    cells.insert(0, {
        "type": "standard.Rectangle",
        "position": {"x": 520, "y": 72},
        "size": {"width": 2170, "height": 1200},
        "angle": 0,
        "data": {"noneConnectable": True, "embeds": embeds_list, "type": "group"},
        "id": main_group_id,
        "attrs": {
            "body": {"stroke": "gray", "strokeDasharray": "8,10"},
            "label": {"textVerticalAnchor": "top", "refY": "100%", "fontSize": 40, "text": "Match the components with their use cases", "textWrap": None, "refY2": 10}
        }
    })

    return {"cells": cells}

def get_dynamic_statements_from_ai(game_data):
    """
    Uses Gemini AI to generate dynamic challenge, learning, congratulations, and sorry statements
    based on the extracted game data.
    """
    components_list = [item['component'] for item in game_data]
    use_cases_list = [item['use_case'] for item in game_data]

    prompt = (
        f"Generate a 'Challenge', 'What User Will Learn', 'Congratulations', and 'Sorry' message "
        f"for a drag-and-drop game. The game involves matching the following components to their use cases:\n"
        f"Components: {', '.join(components_list)}\n"
        f"Use Cases: {'; '.join(use_cases_list)}\n\n"
        f"Each message should be 3-4 lines long and include relevant emojis. "
        f"Format the output strictly as a JSON object with keys: 'Challenge', 'What User Will Learn', 'Congratulations', 'Sorry'."
    )

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "Challenge": {"type": "STRING"},
            "What User Will Learn": {"type": "STRING"},
            "Congratulations": {"type": "STRING"},
            "Sorry": {"type": "STRING"}
        },
        "required": ["Challenge", "What User Will Learn", "Congratulations", "Sorry"], # Ensure all statements are present
        "propertyOrdering": ["Challenge", "What User Will Learn", "Congratulations", "Sorry"]
    }

    statements = call_gemini_api(prompt, response_schema=response_schema)
    
    # Validate statements structure
    if not isinstance(statements, dict) or \
       not all(key in statements and isinstance(statements[key], str) for key in response_schema["properties"]):
        app.logger.warning("AI failed to generate valid dynamic statements. Using generic statements.")
        return {
            "Challenge": "Ready to unravel the secrets of cloud components? 🕵️‍♀️ Drag and drop each item to its correct use case. Sharpen your knowledge and build the perfect architecture! 🏗️",
            "What User Will Learn": "By playing this game, you'll master core cloud services for various tasks. 🧠 Understand how different components fit into a robust strategy. 🚀",
            "Congratulations": "🎉 Fantastic job! You've successfully matched all the components to their use cases! Your architecture knowledge is truly impressive. Keep up the great work! 🏆",
            "Sorry": "😔 Almost there! Some of your matches weren't quite right. Don't worry, every mistake is a step towards mastery! Review the hints and try again to perfect your architecture. 💪"
        }
    return statements


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            document_raw_text = parse_docx_for_raw_text(filepath)
            app.logger.info(f"Extracted raw text from document:\n{document_raw_text[:500]}...") # Log extracted text
            if not document_raw_text:
                return jsonify({"error": "Could not extract any text from the document. Please ensure it contains readable content."}), 400

            # Use AI to get structured game data
            game_data = get_structured_game_data_from_ai(document_raw_text)
            if not game_data:
                app.logger.error("Failed to get game data from AI, or AI returned empty/invalid data.")
                return jsonify({"error": "Failed to extract game data from document using AI. Please check document format or try again."}), 500

            # Generate JSON for the game based on AI-structured data
            game_json = generate_game_json(game_data)
            
            # Use AI to get dynamic statements
            statements = get_dynamic_statements_from_ai(game_data)
            if not statements:
                app.logger.error("Failed to get dynamic statements from AI.")
                # Fallback to generic statements if AI fails for statements
                statements = {
                    "Challenge": "Ready to unravel the secrets of cloud components? 🕵️‍♀️ Drag and drop each item to its correct use case. Sharpen your knowledge and build the perfect architecture! 🏗️",
                    "What User Will Learn": "By playing this game, you'll master core cloud services for various tasks. 🧠 Understand how different components fit into a robust strategy. 🚀",
                    "Congratulations": "🎉 Fantastic job! You've successfully matched all the components to their use cases! Your architecture knowledge is truly impressive. Keep up the great work! 🏆",
                    "Sorry": "😔 Almost there! Some of your matches weren't quite right. Don't worry, every mistake is a step towards mastery! Review the hints and try again to perfect your architecture. 💪"
                }

            return jsonify({
                "json": json.dumps(game_json, indent=2),
                "statements": statements
            })
        except Exception as e:
            app.logger.error(f"An unexpected error occurred during file processing: {e}", exc_info=True)
            return jsonify({"error": f"An unexpected error occurred: {e}"}), 500
    else:
        return jsonify({"error": "Invalid file type. Only .docx files are allowed."}), 400

if __name__ == '__main__':
    app.run(debug=True)
