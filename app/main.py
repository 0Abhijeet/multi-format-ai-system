from fastapi import FastAPI, UploadFile, File
from app.agents.classifier_agent import classify
from app.agents.email_agent import process_email
from app.agents.json_agent import process_json
from app.agents.pdf_agent import process_pdf
from app.router.action_router import route_action
from app.memory.store import memory_store
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
import os
app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/")
def root():
    return {"message": "Welcome to the Multi-Format AI System API"}

@app.post("/process")
async def process(file: UploadFile = File(...)):
    content = await file.read()

    # Step 1: Classify format + intent
    classification = classify(content, file.filename)

    # Step 2: Route to the appropriate agent
    try:
        if classification["format"] == "Email":
            result = process_email(content)
        elif classification["format"] == "JSON":
            result = process_json(content)
        elif classification["format"] == "PDF":
            result = process_pdf(content)
        else:
            result = {"error": "Unsupported format"}
    except Exception as e:
        result = {"error": str(e)}

    # Step 3: Add detected intent from classifier into result
    if "intent" in classification:
        result["intent"] = classification["intent"]

    # Step 4: Trigger chained action
    action_result = route_action(result)

    # Step 5: Store full trace in memory
    memory_store["logs"].append({
        "classification": classification,
        "result": result,
        "action": action_result,
    })

    # Step 6: Return response
    return {
        "classification": classification,
        "result": result,
        "action": action_result
    }

@app.get("/logs")
def get_logs():
    return memory_store["logs"]
@app.get("/ui", response_class=HTMLResponse)
def render_ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

