from app.contracts.vision_gateway import extract_calendar_events_from_image

async def extract_calendar_from_image(img_bytes: bytes, mime_type: str) -> dict:
    return await extract_calendar_events_from_image(img_bytes, mime_type)
