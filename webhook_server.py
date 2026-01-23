from flask import Flask, request

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.get_json()
    print("=== Webhook受信 ===")
    print(body)

    # グループIDが含まれていれば表示
    if body and "events" in body:
        for event in body["events"]:
            src = event.get("source", {})
            if src.get("type") == "group":
                print(f"グループID: {src.get('groupId')}")

    return "OK", 200

if __name__ == "__main__":
    app.run(port=5000)