#!/usr/bin/env bash
# Render Build Script for Route.it (Native Python + Node.js Environment)
set -o errexit

echo "==> Building Route.it Frontend SPA..."
cd frontend
npm install
npm run build
cd ..

echo "==> Installing Route.it Python Backend & Optimization Engine..."
pip install --upgrade pip
pip install -e .

echo "==> Build completed successfully!"
