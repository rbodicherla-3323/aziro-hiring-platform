
import os
from google import genai
from google.genai.errors import APIError
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    AI_CLIENT = genai.Client(api_key=GEMINI_API_KEY)
else:
    AI_CLIENT = None
    print("Warning: GEMINI_API_KEY not set. AI_CLIENT will be None.")


def generate_evaluation_summary(candidate_data):
    """
    Generate an AI-based summary for a candidate's evaluation.
    candidate_data: dict containing candidate's evaluation details.
    Returns a summary string or None.
    """
    if not AI_CLIENT:
        print("Gemini AI client not initialized.")
        return None

    prompt = prompt = f""" 
    Rewrite the following candidate evaluation summary into a professional, 
    HR-readable narrative while preserving factual content. 
    
    Make sure to note that the TA team will go through the evaluation summary. Make it more generalised.
    If the evaluation logic is correct but the output was not fetched in the code, 
    provide a relevant summary instead of leaving it blank. 
    Draft Summary: {candidate_data} """

    try:
        response = AI_CLIENT.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"Error generating summary: {e}")
        return None