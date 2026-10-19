import os
import requests
from dotenv import load_dotenv
from datetime import datetime

import base64

load_dotenv()

def get_access_token():
    consumer_key = os.getenv("CONSUMER_KEY")
    consumer_secret = os.getenv("CONSUMER_SECRET")

    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate"
    params={
        "grant_type" : "client_credentials"
        }

    response = requests.get(
        url,
        auth=(consumer_key, consumer_secret),
        params=params

        )
    response.raise_for_status()

    access_token = response.json()["access_token"]

    return access_token

#========================================================
#INITIATE PAYMENT
#=======================================================
def initiate_payment(order_id, phone_number, amount):
    access_token = get_access_token()

    timestamp =datetime.now().strftime("%Y%m%d%H%M%S")

    shortcode = os.getenv("MPESA_SHORTCODE")
    passkey = os.getenv("MPESA_PASSKEY")

    password_string = shortcode + passkey + timestamp

    password = base64.b64encode(
        password_string.encode()
    ).decode()

    url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    phone_number = phone_number.replace("+", "")


    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": shortcode,
        "PhoneNumber": phone_number,
        "CallBackURL": os.getenv("CALLBACK_URL"),
        "AccountReference": order_id[-12:],
        "TransactionDesc": "Tobhe payment"
    }
    response = requests.post(
        url,
        json=payload,
        headers={"authorization":f"Bearer {access_token}"}
    )
    print("Safaricom status:", response.status_code)
    print("Safaricom response:", response.text)

    response.raise_for_status()
    return response.json()

#====================================================
# QUERY STK PUSH STATUS
#====================================================
def query_stk_status(checkout_request_id):
    access_token = get_access_token()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    shortcode = os.getenv("MPESA_SHORTCODE")
    passkey = os.getenv("MPESA_PASSKEY")

    password_string = shortcode + passkey + timestamp

    password = base64.b64encode(
        password_string.encode()
        ).decode()

    payload = {
        "BusinessShortCode":shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id
    }
    url = "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query"

    headers = {
    "Authorization": f"Bearer {access_token}"
}
    response = requests.post(
    url,
    json=payload,
    headers=headers
)
    print("STK Query status:", response.status_code)
    print("STK Query response:", response.text)

    response.raise_for_status()

    return response.json()
