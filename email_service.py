# ChatGPT also used for troubleshooting, suggestions and generating and setup of SMTP
from graph_mail import send_graph_email

def send_email(to_email: str, subject: str, body: str) -> None:
    return send_graph_email(to_email, subject, body)
