import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import app

# Use the create_app function properly
flask_app = app.create_app()
print("Flask app created via create_app():", type(flask_app))
