## backend/app.py

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.requests import Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import boto3
import json

# Initialize AWS services
s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
cloudwatch = boto3.client('cloudwatch')

# Initialize FastAPI app
app = FastAPI()

# Define user model
class User(BaseModel):
    id: str
    username: str
    email: str

# Define game analytics model
class GameAnalytics(BaseModel):
    game_id: str
    player_id: str
    analytics_data: str

# Define API endpoints

# User Management
@app.post("/users")
async def create_user(user: User):
    # Create new user account in DynamoDB
    table = dynamodb.Table('users')
    table.put_item(Item=user.dict())
    return JSONResponse(content={"message": "User created successfully"}, status_code=201)

@app.get("/users/{user_id}")
async def get_user(user_id: str):
    # Retrieve user profile from DynamoDB
    table = dynamodb.Table('users')
    try:
        user = table.get_item(Key={'id': user_id})['Item']
        return JSONResponse(content=user, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=404, detail="User not found")

@app.put("/users/{user_id}")
async def update_user(user_id: str, user: User):
    # Update user profile in DynamoDB
    table = dynamodb.Table('users')
    table.update_item(Key={'id': user_id}, UpdateExpression='set #username = :username, #email = :email',
                      ExpressionAttributeNames={'#username': 'username', '#email': 'email'},
                      ExpressionAttributeValues={':username': user.username, ':email': user.email})
    return JSONResponse(content={"message": "User updated successfully"}, status_code=200)

# Gaming Analytics
@app.post("/games/{game_id}/analytics")
async def send_game_analytics(game_id: str, analytics_data: GameAnalytics):
    # Send game analytics data to DynamoDB
    table = dynamodb.Table('game_analytics')
    table.put_item(Item=analytics_data.dict())
    return JSONResponse(content={"message": "Game analytics data sent successfully"}, status_code=201)

@app.get("/games/{game_id}/analytics")
async def get_game_analytics(game_id: str):
    # Retrieve game analytics data from DynamoDB
    table = dynamodb.Table('game_analytics')
    try:
        analytics_data = table.scan(FilterExpression=Attr('game_id').eq(game_id))['Items']
        return JSONResponse(content=analytics_data, status_code=200)
    except Exception as e:
        raise