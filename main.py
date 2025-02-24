import os
import json
import requests
from fastapi import FastAPI, HTTPException, Form
from fastapi.responses import FileResponse

app = FastAPI()

def generate_image_and_download(prompt: str, id_image: str) -> str:
    # Base API endpoint for image generation
    base_url = "https://yanze-pulid-flux.hf.space/call/generate_image"
    
    # JSON payload with 13 custom parameters
    payload = {
        "data": [
            prompt,   # Prompt text
            {"path": id_image},  # ID image file
            0,        # start_step
            4,        # guidance
            "-1",     # seed ("-1" for random)
            1,        # true_cfg
            896,      # width
            1152,     # height
            20,       # num_steps
            1,        # id_weight
            "bad quality, worst quality, text, signature, watermark, extra limbs",  # neg_prompt
            1,        # timestep_to_start_cfg
            128       # max_sequence_length
        ]
    }
    headers = {"Content-Type": "application/json"}
    
    # Send the initial POST request
    response = requests.post(base_url, json=payload, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Error in POST request: {response.text}")
    
    # Extract event ID from the response (using splitting as in your shell command)
    try:
        event_id = response.text.split('"')[3]
    except IndexError:
        raise HTTPException(status_code=500, detail="Failed to extract event ID from response.")
    
    # Poll the event endpoint to get the streaming response
    poll_url = f"{base_url}/{event_id}"
    complete_event_received = False
    data_buffer = []
    
    try:
        with requests.get(poll_url, stream=True) as poll_response:
            if poll_response.status_code != 200:
                raise HTTPException(status_code=poll_response.status_code, detail=f"Error while polling event: {poll_response.text}")
            for line in poll_response.iter_lines(decode_unicode=True):
                if not line:
                    if complete_event_received and data_buffer:
                        break
                    data_buffer = []
                    continue

                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                    if event_type == "complete":
                        complete_event_received = True
                elif line.startswith("data:"):
                    data_line = line[len("data:"):].strip()
                    if complete_event_received:
                        data_buffer.append(data_line)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error while polling: {e}")

    if not data_buffer:
        raise HTTPException(status_code=500, detail="No complete event data received.")

    complete_event_data = "\n".join(data_buffer)
    try:
        json_data = json.loads(complete_event_data)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"JSON decode error: {e}")

    # Extract the image path from the JSON response.
    if isinstance(json_data, list) and len(json_data) > 0 and isinstance(json_data[0], dict) and "path" in json_data[0]:
        image_path = json_data[0]["path"]
    else:
        raise HTTPException(status_code=500, detail="Could not extract image path from response JSON.")
    
    # Construct the download URL
    download_base_url = "https://yanze-pulid-flux.hf.space/file="
    download_url = f"{download_base_url}{image_path}"
    
    # Download the image file
    try:
        image_response = requests.get(download_url, stream=True)
        if image_response.status_code == 200:
            # Use the original filename from the image path
            filename = image_path.split("/")[-1]
            with open(filename, "wb") as f:
                for chunk in image_response.iter_content(chunk_size=1024):
                    f.write(chunk)
            return filename
        else:
            raise HTTPException(status_code=image_response.status_code, detail="Failed to download image.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading image: {e}")

@app.post("/generate")
async def generate(prompt: str = Form(...), id_image: str = Form(...)):
    """
    Expects form data with 'prompt' and 'id_image' keys.
    When complete, returns the generated image file.
    """
    filename = generate_image_and_download(prompt, id_image)
    if os.path.exists(filename):
        return FileResponse(path=filename, filename=filename, media_type="application/octet-stream")
    else:
        raise HTTPException(status_code=500, detail="Image file not found after generation.")
