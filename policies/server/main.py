from flask import Flask
from flask_cors import CORS
from .api import api_bp

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

app.register_blueprint(api_bp, url_prefix='/api')

@app.route('/health')
def health_check():
    return {"status": "ok"}

if __name__ == '__main__':
    app.run(port=8000, debug=True)
