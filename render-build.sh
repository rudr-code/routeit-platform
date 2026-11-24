#!/usr/bin/env bash
# Render Build Script for Route.it (Root workspace level)
set -o errexit

echo "==> Building Route.it Frontend SPA..."
cd routeit/frontend
npm install
npm run build
cd ../..

echo "==> Installing Route.it Python Backend & Optimization Engine..."
pip install --upgrade pip
pip install -e routeit

echo "==> Build completed successfully!"
