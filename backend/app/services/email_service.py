import asyncio
import smtplib
import time

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, formataddr, make_msgid
from app.core.config import settings
from app.core.logging import logger

# In-memory thread-safe cache for duplicate email prevention
# Maps (normalized_to_email, normalized_subject) -> timestamp
_sent_email_cache: dict[tuple[str, str], float] = {}
_cache_lock = asyncio.Lock()
_DEDUP_WINDOW_SECONDS = 120  # 2-minute deduplication window to prevent duplicate sends

async def _is_duplicate_send(to_email: str, subject: str, window_seconds: int = _DEDUP_WINDOW_SECONDS) -> bool:
    """
    Check if an identical email was recently sent to the same recipient.
    Returns True if duplicate (should be suppressed), False otherwise.
    """
    norm_key = (to_email.strip().lower(), subject.strip())
    now = time.time()

    async with _cache_lock:
        # Prune expired entries to keep memory bounded
        expired = [k for k, ts in _sent_email_cache.items() if now - ts > window_seconds]
        for k in expired:
            _sent_email_cache.pop(k, None)

        last_sent = _sent_email_cache.get(norm_key)
        if last_sent is not None and (now - last_sent) < window_seconds:
            logger.warning(
                f"[EmailService] Duplicate email suppressed for {to_email} with subject '{subject}'. "
                f"Previous send was {now - last_sent:.1f}s ago."
            )
            return True

        _sent_email_cache[norm_key] = now
        return False

def _send_email_sync(to_email: str, subject: str, html_content: str, text_content: str = "") -> None:
    """Synchronous helper using smtplib (STARTTLS) to send email."""
    if not settings.SMTP_USER or not settings.SMTP_PASS:
        logger.warning(f"SMTP credentials not configured. Skipping email to {to_email}")
        return

    # Extract domain from SMTP_USER for Message-ID
    sender_domain = settings.SMTP_USER.split("@")[-1] if "@" in settings.SMTP_USER else "localhost"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.EMAILS_FROM_NAME, settings.SMTP_USER))
    msg["To"] = to_email
    msg["Reply-To"] = settings.SMTP_USER
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender_domain)
    msg["MIME-Version"] = "1.0"
    msg["X-Mailer"] = f"{settings.APP_NAME} Mailer"

    # Always attach plain-text part first (HTML-only emails trigger spam filters)
    if text_content:
        msg.attach(MIMEText(text_content, "plain", "utf-8"))
    if html_content:
        msg.attach(MIMEText(html_content, "html", "utf-8"))

    sent = False
    last_error = None
    try:
        server = smtplib.SMTP(settings.EMAIL_SERVER_HOST, settings.EMAIL_SERVER_PORT, timeout=15)
        try:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASS)
            server.sendmail(settings.SMTP_USER, [to_email], msg.as_string())
            logger.info(f"Successfully sent email to {to_email}: {subject}")
            sent = True
        finally:
            try:
                server.quit()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"SMTP port {settings.EMAIL_SERVER_PORT} failed for {to_email}: {e}. Trying SSL port 465 fallback...")
        last_error = e

    if not sent:
        try:
            server = smtplib.SMTP_SSL(settings.EMAIL_SERVER_HOST, 465, timeout=15)
            try:
                server.login(settings.SMTP_USER, settings.SMTP_PASS)
                server.sendmail(settings.SMTP_USER, [to_email], msg.as_string())
                logger.info(f"Successfully sent email via fallback port 465 to {to_email}: {subject}")
                sent = True
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to send email to {to_email} on fallback port 465: {e}")
            raise last_error or e


async def send_email_async(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str = "",
    allow_duplicate: bool = False
) -> None:
    """Async wrapper around smtplib with automatic deduplication protection."""
    if not allow_duplicate and await _is_duplicate_send(to_email, subject):
        return

    await asyncio.to_thread(_send_email_sync, to_email, subject, html_content, text_content)

PUNK_TOP_LOGO_HTML = """
<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin: 0 auto;">
  <tr>
    <td align="center" valign="middle">
      <img
        src="https://pub-073174804afb431b98e7e820305acced.r2.dev/uploads/1789140481922-d0c4qu-group-54.png"
        alt="Punk AI"
        width="121"
        style="display: block; border: 0; outline: none; text-decoration: none; width: 121px; max-width: 100%; height: auto; margin: 0 auto;"
      />
    </td>
  </tr>
</table>
"""
PUNK_TOP_LOGO_SVG = PUNK_TOP_LOGO_HTML

async def send_verification_otp_email(to_email: str, code: str) -> None:
    subject = f"{code} is your Punk AI verification code"
    text_content = f"Your verification code is: {code}. It will expire in 10 minutes."

    otp_digits_html = ""
    for digit in code:
        otp_digits_html += f"""
            <td align="center" valign="middle" style="padding: 0 5px; width: 64px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="64" height="72" style="width: 64px; height: 72px; border: 1px solid #F54397; border-radius: 15px; background-color: #ffffff;">
                <tr>
                  <td align="center" valign="middle" style="font-family: 'Geist', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 32px; font-weight: 700; color: #000000; line-height: 72px; text-align: center;">
                    {digit}
                  </td>
                </tr>
              </table>
            </td>"""

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en" xmlns="http://www.w3.org/1999/xhtml">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <meta http-equiv="X-UA-Compatible" content="IE=edge">
      <meta name="color-scheme" content="light">
      <meta name="supported-color-schemes" content="light">
      <title>Verify Your Email</title>
      <link rel="preconnect" href="https://fonts.googleapis.com">
      <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
      <link href="https://fonts.googleapis.com/css2?family=Geist:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
      <!--[if mso]>
      <style type="text/css">
        table {{border-collapse: collapse; border-spacing: 0; margin: 0;}}
        div, td {{padding: 0;}}
        div {{margin: 0 !important;}}
      </style>
      <noscript>
        <xml>
          <o:OfficeDocumentSettings>
            <o:PixelsPerInch>96</o:PixelsPerInch>
          </o:OfficeDocumentSettings>
        </xml>
      </noscript>
      <![endif]-->
      <style>
        @media only screen and (max-width: 680px) {{
          .email-container {{
            width: 100% !important;
            padding: 24px 20px 36px 20px !important;
          }}
          .title-text {{
            font-size: 32px !important;
            line-height: 38px !important;
          }}
        }}
      </style>
    </head>
    <body style="
      margin: 0;
      padding: 0;
      width: 100%;
      background-color: #ffffff;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    ">
      <!-- Outer wrapper table -->
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #ffffff; margin: 0; padding: 0;">
        <tr>
          <td align="center" style="padding: 0;">
            <!-- Inner content container -->
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="680" class="email-container" style="max-width: 680px; width: 100%; padding: 30px 60px 48px 60px; margin: 0 auto; box-sizing: border-box;">

              <!-- Top Brand Logo -->
              <tr>
                <td align="center" style="padding: 0 0 20px 0;">
                  {PUNK_TOP_LOGO_SVG}
                </td>
              </tr>

              <!-- Illustration / Shield Mascot Graphic -->
              <tr>
                <td align="center" style="padding: 0 0 24px 0;">
                  <img
                    src="https://pub-073174804afb431b98e7e820305acced.r2.dev/uploads/1789072318257-majdad-logo-container.png"
                    alt="{settings.APP_NAME}"
                    width="200"
                    style="display: block; border: 0; outline: none; text-decoration: none; width: 200px; max-width: 100%; height: auto; margin: 0 auto;"
                  />
                </td>
              </tr>

              <!-- Heading -->
              <tr>
                <td align="center" style="padding: 0 0 16px 0;">
                  <h1 class="title-text" style="
                    margin: 0;
                    color: #000000;
                    font-feature-settings: 'liga' off, 'clig' off;
                    font-family: 'Geist', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 40px;
                    font-style: normal;
                    font-weight: 700;
                    line-height: 44px;
                    text-align: center;
                    letter-spacing: -0.5px;
                  ">Verify Your Email</h1>
                </td>
              </tr>

              <!-- Subtitle / Instruction -->
              <tr>
                <td align="center" style="padding: 0 20px 32px 20px;">
                  <p style="
                    margin: 0;
                    color: #303030;
                    text-align: center;
                    font-feature-settings: 'liga' off, 'clig' off;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 16px;
                    font-style: normal;
                    font-weight: 400;
                    line-height: 24px;
                  ">We received a request to verify your email for your {settings.APP_NAME} account. Use the verification code below to complete your sign-up. This code will expire in 10 minutes.</p>
                </td>
              </tr>

              <!-- OTP Code Section -->
              <tr>
                <td align="center" style="padding: 0 0 28px 0;">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin: 0 auto;">
                    <tr>
                      {otp_digits_html}
                    </tr>
                  </table>
                </td>
              </tr>

              <!-- Subtext / Security Notice -->
              <tr>
                <td align="center" style="padding: 0 20px 0 20px;">
                  <p style="
                    margin: 0;
                    color: #303030;
                    text-align: center;
                    font-feature-settings: 'liga' off, 'clig' off;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 14px;
                    font-style: normal;
                    font-weight: 400;
                    line-height: 22px;
                  ">If you didn't make this request, you can safely ignore this email.</p>
                </td>
              </tr>

              <!-- Divider -->
              <tr>
                <td align="center" style="padding: 36px 0 24px 0;">
                  <div style="height: 1px; background-color: #F0F0F0; width: 100%;"></div>
                </td>
              </tr>

              <!-- Footer -->
              <tr>
                <td align="center" style="padding: 0 20px 0 20px;">
                  <p style="
                    margin: 0 0 12px 0;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 13px;
                    font-weight: 400;
                    color: #9CA3AF;
                    line-height: 1.8;
                    text-align: center;
                  ">Questions about Punk? No worries!!! Ping us at
                    <a href="mailto:noreply@usepunk.ai" style="color: #F54397; text-decoration: none;">noreply@usepunk.ai</a>
                    or visit
                    <a href="https://usepunk.ai/support" style="color: #F54397; text-decoration: none;">usepunk.ai/support</a>
                  </p>
                  <p style="
                    margin: 0;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 12px;
                    font-weight: 400;
                    color: #9CA3AF;
                    text-align: center;
                  ">&copy; {settings.APP_NAME} all rights reserved</p>
                </td>
              </tr>

            </table>
            <!-- /Inner content container -->
          </td>
        </tr>
      </table>
      <!-- /Outer wrapper table -->
    </body>
    </html>
    """
    await send_email_async(to_email, subject, html_content, text_content, allow_duplicate=True)

async def send_password_reset_otp_email(to_email: str, code: str) -> None:
    subject = f"{code} is your Punk AI password reset code"
    text_content = f"Your password reset code is: {code}. It will expire in 10 minutes."

    # Build individual OTP digit cells for the code
    otp_digits_html = ""
    for digit in code:
        otp_digits_html += f"""
            <td align="center" valign="middle" style="padding: 0 5px; width: 64px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="64" height="72" style="width: 64px; height: 72px; border: 1px solid #F54397; border-radius: 15px; background-color: #ffffff;">
                <tr>
                  <td align="center" valign="middle" style="font-family: 'Geist', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 32px; font-weight: 700; color: #000000; line-height: 72px; text-align: center;">
                    {digit}
                  </td>
                </tr>
              </table>
            </td>"""

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en" xmlns="http://www.w3.org/1999/xhtml">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <meta http-equiv="X-UA-Compatible" content="IE=edge">
      <meta name="color-scheme" content="light">
      <meta name="supported-color-schemes" content="light">
      <title>Reset Your Password</title>
      <link rel="preconnect" href="https://fonts.googleapis.com">
      <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
      <link href="https://fonts.googleapis.com/css2?family=Geist:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
      <!--[if mso]>
      <style type="text/css">
        table {{border-collapse: collapse; border-spacing: 0; margin: 0;}}
        div, td {{padding: 0;}}
        div {{margin: 0 !important;}}
      </style>
      <noscript>
        <xml>
          <o:OfficeDocumentSettings>
            <o:PixelsPerInch>96</o:PixelsPerInch>
          </o:OfficeDocumentSettings>
        </xml>
      </noscript>
      <![endif]-->
      <style>
        @media only screen and (max-width: 680px) {{
          .email-container {{
            width: 100% !important;
            padding: 24px 20px 36px 20px !important;
          }}
          .title-text {{
            font-size: 32px !important;
            line-height: 38px !important;
          }}
        }}
      </style>
    </head>
    <body style="
      margin: 0;
      padding: 0;
      width: 100%;
      background-color: #ffffff;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    ">
      <!-- Outer wrapper table -->
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #ffffff; margin: 0; padding: 0;">
        <tr>
          <td align="center" style="padding: 0;">
            <!-- Inner content container -->
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="680" class="email-container" style="max-width: 680px; width: 100%; padding: 30px 60px 48px 60px; margin: 0 auto; box-sizing: border-box;">

              <!-- Top Brand Logo -->
              <tr>
                <td align="center" style="padding: 0 0 20px 0;">
                  {PUNK_TOP_LOGO_SVG}
                </td>
              </tr>

              <!-- Illustration / Shield Mascot Graphic -->
              <tr>
                <td align="center" style="padding: 0 0 24px 0;">
                  <img
                    src="https://pub-073174804afb431b98e7e820305acced.r2.dev/uploads/1789072318257-majdad-logo-container.png"
                    alt="{settings.APP_NAME}"
                    width="200"
                    style="display: block; border: 0; outline: none; text-decoration: none; width: 200px; max-width: 100%; height: auto; margin: 0 auto;"
                  />
                </td>
              </tr>

              <!-- Heading -->
              <tr>
                <td align="center" style="padding: 0 0 16px 0;">
                  <h1 class="title-text" style="
                    margin: 0;
                    color: #000000;
                    font-feature-settings: 'liga' off, 'clig' off;
                    font-family: 'Geist', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 40px;
                    font-style: normal;
                    font-weight: 700;
                    line-height: 44px;
                    text-align: center;
                    letter-spacing: -0.5px;
                  ">Reset Your Password</h1>
                </td>
              </tr>

              <!-- Subtitle / Instruction -->
              <tr>
                <td align="center" style="padding: 0 20px 32px 20px;">
                  <p style="
                    margin: 0;
                    color: #303030;
                    text-align: center;
                    font-feature-settings: 'liga' off, 'clig' off;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 16px;
                    font-style: normal;
                    font-weight: 400;
                    line-height: 24px;
                  ">We received a request to reset the password for your {settings.APP_NAME} account. Use the verification code below to choose a new password. This code will expire in 10 minutes.</p>
                </td>
              </tr>

              <!-- OTP Code Section -->
              <tr>
                <td align="center" style="padding: 0 0 28px 0;">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin: 0 auto;">
                    <tr>
                      {otp_digits_html}
                    </tr>
                  </table>
                </td>
              </tr>

              <!-- Subtext / Security Notice -->
              <tr>
                <td align="center" style="padding: 0 20px 0 20px;">
                  <p style="
                    margin: 0;
                    color: #303030;
                    text-align: center;
                    font-feature-settings: 'liga' off, 'clig' off;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 14px;
                    font-style: normal;
                    font-weight: 400;
                    line-height: 22px;
                  ">If you didn't make this request, you can safely ignore this email. Your password will remain unchanged.</p>
                </td>
              </tr>

              <!-- Divider -->
              <tr>
                <td align="center" style="padding: 36px 0 24px 0;">
                  <div style="height: 1px; background-color: #F0F0F0; width: 100%;"></div>
                </td>
              </tr>

              <!-- Footer -->
              <tr>
                <td align="center" style="padding: 0 20px 0 20px;">
                  <p style="
                    margin: 0 0 12px 0;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 13px;
                    font-weight: 400;
                    color: #9CA3AF;
                    line-height: 1.8;
                    text-align: center;
                  ">Questions about Punk? No worries!!! Ping us at
                    <a href="mailto:noreply@usepunk.ai" style="color: #F54397; text-decoration: none;">noreply@usepunk.ai</a>
                    or visit
                    <a href="https://usepunk.ai/support" style="color: #F54397; text-decoration: none;">usepunk.ai/support</a>
                  </p>
                  <p style="
                    margin: 0;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 12px;
                    font-weight: 400;
                    color: #9CA3AF;
                    text-align: center;
                  ">&copy; {settings.APP_NAME} all rights reserved</p>
                </td>
              </tr>

            </table>
            <!-- /Inner content container -->
          </td>
        </tr>
      </table>
      <!-- /Outer wrapper table -->
    </body>
    </html>
    """
    await send_email_async(to_email, subject, html_content, text_content, allow_duplicate=True)


async def send_early_access_access_link_email(to_email: str, access_link: str) -> None:
    subject = "You're in! Welcome to Punk Early Access"
    text_content = (
        f"You're in!\n\n"
        f"Your payment was successful and your beta spot is officially confirmed.\n\n"
        f"You're one step away from getting started with Punk — AI-powered audience intelligence "
        f"built to help you find the right people, on the right devices, in the right places.\n\n"
        f"Complete your registration here:\n{access_link}\n\n"
        f"Once you've completed registration, you'll be able to set up your account and start exploring Punk."
    )
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en" xmlns="http://www.w3.org/1999/xhtml">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <meta http-equiv="X-UA-Compatible" content="IE=edge">
      <meta name="color-scheme" content="light">
      <meta name="supported-color-schemes" content="light">
      <title>You're in! Welcome to Punk</title>
      <link rel="preconnect" href="https://fonts.googleapis.com">
      <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
      <link href="https://fonts.googleapis.com/css2?family=Geist:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
      <!--[if mso]>
      <style type="text/css">
        table {{border-collapse: collapse; border-spacing: 0; margin: 0;}}
        div, td {{padding: 0;}}
        div {{margin: 0 !important;}}
      </style>
      <noscript>
        <xml>
          <o:OfficeDocumentSettings>
            <o:PixelsPerInch>96</o:PixelsPerInch>
          </o:OfficeDocumentSettings>
        </xml>
      </noscript>
      <![endif]-->
      <style>
        @media only screen and (max-width: 680px) {{
          .email-container {{
            width: 100% !important;
            padding: 24px 20px 36px 20px !important;
          }}
          .title-text {{
            font-size: 32px !important;
            line-height: 38px !important;
          }}
        }}
      </style>
    </head>
    <body style="
      margin: 0;
      padding: 0;
      width: 100%;
      background-color: #ffffff;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    ">
      <!-- Outer wrapper table -->
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #ffffff; margin: 0; padding: 0;">
        <tr>
          <td align="center" style="padding: 0;">
            <!-- Inner content container -->
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="680" class="email-container" style="max-width: 680px; width: 100%; padding: 30px 60px 48px 60px; margin: 0 auto; box-sizing: border-box;">

              <!-- Top Brand Logo -->
              <tr>
                <td align="center" style="padding: 0 0 72px 0;">
                  <img
                    src="https://pub-073174804afb431b98e7e820305acced.r2.dev/uploads/1789140481922-d0c4qu-group-54.png"
                    alt="Punk AI"
                    width="121"
                    style="display: block; border: 0; outline: none; text-decoration: none; width: 121px; max-width: 100%; height: auto; margin: 0 auto;"
                  />
                </td>
              </tr>

              <!-- Welcome Hero Illustration Graphic -->
              <tr>
                <td align="center" style="padding: 0 0 28px 0;">
                  <img
                    src="https://pub-073174804afb431b98e7e820305acced.r2.dev/uploads/1789072546242-ui3pgk-frame-2147259293.png"
                    alt="Welcome to Punk AI"
                    width="300"
                    style="display: block; border: 0; outline: none; text-decoration: none; width: 300px; max-width: 100%; height: auto; margin: 0 auto;"
                  />
                </td>
              </tr>

              <!-- Eyebrow Badge -->
              <tr>
                <td align="center" style="padding: 0 0 8px 0;">
                  <span style="
                    display: inline-block;
                    color: #F54397;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 13px;
                    font-weight: 600;
                    letter-spacing: 1.5px;
                    text-transform: uppercase;
                    text-align: center;
                  ">EARLY ACCESS SECURED</span>
                </td>
              </tr>

              <!-- Heading -->
              <tr>
                <td align="center" style="padding: 0 0 20px 0;">
                  <h1 class="title-text" style="
                    margin: 0;
                    color: #000000;
                    font-feature-settings: 'liga' off, 'clig' off;
                    font-family: 'Geist', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 40px;
                    font-style: normal;
                    font-weight: 700;
                    line-height: 44px;
                    text-align: center;
                    letter-spacing: -0.5px;
                  ">You're in!</h1>
                </td>
              </tr>

              <!-- Body Paragraphs -->
              <tr>
                <td align="center" style="padding: 0 20px 14px 20px;">
                  <p style="
                    margin: 0;
                    color: #303030;
                    text-align: center;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 16px;
                    font-weight: 400;
                    line-height: 24px;
                  ">Your payment was successful and your beta spot is officially confirmed.</p>
                </td>
              </tr>

              <tr>
                <td align="center" style="padding: 0 20px 32px 20px;">
                  <p style="
                    margin: 0;
                    color: #303030;
                    text-align: center;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 16px;
                    font-weight: 400;
                    line-height: 24px;
                  ">You're one step away from getting started with Punk &mdash; AI-powered audience intelligence built to help you find the <strong>right people, on the right devices, in the right places</strong>.</p>
                </td>
              </tr>

              <!-- Call To Action Button -->
              <tr>
                <td align="center" style="padding: 0 0 32px 0;">
                  <!--[if mso]>
                  <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{access_link}" style="height:48px;v-text-anchor:middle;width:260px;" arcsize="50%" stroke="f" fillcolor="#222222">
                    <w:anchorlock/>
                    <center style="color:#ffffff;font-family:sans-serif;font-size:15px;font-weight:600;">Complete Your Registration</center>
                  </v:roundrect>
                  <![endif]-->
                  <!--[if !mso]><!-- -->
                  <a href="{access_link}" style="
                    display: inline-block;
                    background: #222222;
                    color: #ffffff;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 15px;
                    font-weight: 600;
                    text-decoration: none;
                    padding: 15px 36px;
                    border-radius: 40px;
                    box-shadow: 0 10px 25px rgba(0,0,0,0.3);
                    text-align: center;
                  ">Complete Your Registration</a>
                  <!--<![endif]-->
                </td>
              </tr>

              <!-- Fallback Link Notice -->
              <tr>
                <td align="center" style="padding: 0 20px 0 20px;">
                  <p style="
                    margin: 0;
                    color: #6B7280;
                    text-align: center;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 14px;
                    font-weight: 400;
                    line-height: 22px;
                  ">If the button above doesn't work, copy and paste this link into your browser:<br/>
                    <a href="{access_link}" style="color: #222222; font-weight: 600; word-break: break-all; text-decoration: none;">{access_link}</a>
                  </p>
                </td>
              </tr>

              <!-- Divider -->
              <tr>
                <td align="center" style="padding: 36px 0 24px 0;">
                  <div style="height: 1px; background-color: #F0F0F0; width: 100%;"></div>
                </td>
              </tr>

              <!-- Footer -->
              <tr>
                <td align="center" style="padding: 0 20px 0 20px;">
                  <p style="
                    margin: 0 0 16px 0;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 13px;
                    font-weight: 400;
                    color: #9CA3AF;
                    line-height: 1.6;
                    text-align: center;
                  ">Once you've completed registration, you'll be able to set up your account and start exploring Punk.</p>
                  <p style="
                    margin: 0;
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 12px;
                    font-weight: 400;
                    color: #9CA3AF;
                    text-align: center;
                  ">&copy; PunkAI all rights reserved</p>
                </td>
              </tr>

            </table>
            <!-- /Inner content container -->
          </td>
        </tr>
      </table>
      <!-- /Outer wrapper table -->
    </body>
    </html>
    """
    await send_email_async(to_email, subject, html_content, text_content)

