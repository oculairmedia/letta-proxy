# 1. Use Node.js 20-alpine base image
FROM node:20-alpine

# 2. Set working directory to /app
WORKDIR /app

# 3. Copy package*.json and install dependencies
COPY package*.json ./
RUN npm install

# 4. Copy source files
# Copy the rest of the application code
COPY . .

# 5. Add build steps as needed
# Assuming there's a build script in package.json (e.g., for TypeScript compilation)
# If your project doesn't have a build step, you can remove the next line.
RUN npm run build

# 6. Expose port 3000
EXPOSE 8283

# 7. Set startup command
# Replace 'dist/index.js' with the actual path to your compiled main file if different
CMD ["node", "dist/index.js", "--port", "8283"]