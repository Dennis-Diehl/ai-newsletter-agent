import ssl
import smtplib
import time
from datetime import date
from email.message import EmailMessage

from playwright.async_api import async_playwright

from graph.state import NewsletterState
from config.settings import SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO


# --- SMTP config ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT   = 587
EMAIL_USER  = EMAIL_FROM
EMAIL_RECIPIENT = EMAIL_TO
EMAIL_PASS  = SMTP_PASSWORD


async def publish(state: NewsletterState) -> dict:
    """LangGraph node: send the HTML newsletter via Gmail SMTP.

    Generates a PDF from the HTML using Playwright, then sends it as an
    email attachment with up to 3 attempts before giving up.
    """

    # --- Guard ---
    newsletter = state.get("newsletter")
    if newsletter is None:
        print("[publisher] no newsletter to send.")
        return {"sent": False}

    # --- Generate PDF ---
    print("[publisher] generating PDF...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(newsletter.html_content, wait_until="load")
        pdf_bytes = await page.pdf(format="A4", margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"})
        await browser.close()
    print("[publisher] PDF generated.")

    # --- Build email ---
    today = date.today()

    msg = EmailMessage()
    msg["Subject"] = f"Weekly AI Report – {today.strftime('%d.%m.%Y')}"
    msg["From"]    = EMAIL_USER
    msg["To"]      = EMAIL_RECIPIENT

    # Plain-text fallback for mail clients that don't render HTML.
    msg.set_content("Please enable HTML view to read this newsletter.")

    # HTML version 
    msg.add_alternative(newsletter.html_content, subtype="html")

    # PDF attachment for archiving or offline reading.
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=f"newsletter_{today.isoformat()}.pdf",
    )

    # --- Send with retry ---
    context = ssl.create_default_context()

    for attempt in range(3):
        try:
            print(f"[publisher] sending email (attempt {attempt + 1}/3)...")
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
                smtp.starttls(context=context)       # Upgrade connection to TLS.
                smtp.login(EMAIL_USER, EMAIL_PASS)   # Authenticate with app password.
                smtp.send_message(msg)
            print("[publisher] sent.")
            return {"sent": True, "newsletter_pdf": pdf_bytes}

        except (smtplib.SMTPException, OSError) as e:
            if attempt < 2:
                wait = 2 ** attempt * 3
                print(f"[publisher] error (attempt {attempt + 1}/3): {e}")
                print(f"[publisher] retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"[publisher] failed to send after 3 attempts: {e}")

    return {"sent": False, "newsletter_pdf": pdf_bytes}
