## Unit Tests for Backend
const request = require('supertest');
const app = require('../../app');
const User = require('../../models/User');
const Game = require('../../models/Game');

## Test User Authentication
describe('User Authentication', () => {
  it('should create a new user account', async () => {
    const userData = { username: 'testUser', email: 'test@example.com' };
    const response = await request(app).post('/users').send(userData);
    expect(response.status).toBe(201);
    expect(response.body.username).toBe(userData.username);
  });

  it('should authenticate an existing user', async () => {
    const user = await User.create({ username: 'testUser', email: 'test@example.com' });
    const response = await request(app).post('/login').send({ username: user.username, password: 'password' });
    expect(response.status).toBe(200);
    expect(response.body.token).toBeDefined();
  });
});

## Test Game Session Analysis
describe('Game Session Analysis', () => {
  it('should create a new game session', async () => {
    const gameData = { userId: 'testUser', gameTitle: 'Test Game' };
    const response = await request(app).post('/games').send(gameData);
    expect(response.status).toBe(201);
    expect(response.body.gameTitle).toBe(gameData.gameTitle);
  });

  it('should analyze a game session', async () => {
    const game = await Game.create({ userId: 'testUser', gameTitle: 'Test Game' });
    const response = await request(app).get(`/games/${game.id}`);
    expect(response.status).toBe(200);
    expect(response.body.analysisData).toBeDefined();
  });
});

## Test API Endpoint Handlers
describe('API Endpoint Handlers', () => {
  it('should handle GET /users/{id}', async () => {
    const user = await User.create({ username: 'testUser', email: 'test@example.com' });
    const response = await request(app).get(`/users/${user.id}`);
    expect(response.status).toBe(200);
    expect(response.body.username).toBe(user.username);
  });

  it('should handle POST /games', async () => {
    const gameData = { userId: 'testUser', gameTitle: 'Test Game' };
    const response = await request(app).post('/games').send(gameData);
    expect(response.status).toBe(201);
    expect(response.body.gameTitle).toBe(gameData.gameTitle);
  });
});