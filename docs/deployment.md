# Deployment Guide

## Overview

This guide covers deploying the AutoEIA platform to production using Vercel (frontend) and Render (backend).

## Prerequisites

- GitHub account
- Vercel account
- Render account
- Git installed locally

## Frontend Deployment (Vercel)

### Step 1: Prepare Repository

1. Initialize git repository (if not already done):
```bash
cd platform/frontend
git init
git add .
git commit -m "Initial commit"
```

2. Push to GitHub:
```bash
git remote add origin https://github.com/yourusername/autoeia-frontend.git
git push -u origin main
```

### Step 2: Deploy to Vercel

1. Go to [vercel.com](https://vercel.com) and sign in
2. Click "New Project"
3. Import your GitHub repository
4. Configure build settings:
   - **Framework Preset**: Vite
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
   - **Install Command**: `npm install`

5. Add environment variables:
   - `VITE_API_URL`: Your backend URL (e.g., `https://autoeia-backend.onrender.com`)

6. Click "Deploy"

### Step 3: Custom Domain (Optional)

1. In Vercel dashboard, go to Settings → Domains
2. Add your custom domain
3. Update DNS records as instructed

## Backend Deployment (Render)

### Step 1: Prepare Repository

1. Create `render.yaml` in project root:

```yaml
services:
  - type: web
    name: autoeia-backend
    env: python
    buildCommand: "cd platform/backend && pip install -r requirements.txt"
    startCommand: "cd platform/backend && gunicorn app:app"
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.0
```

2. Add `gunicorn` to `requirements.txt`:
```bash
cd platform/backend
echo "gunicorn==21.2.0" >> requirements.txt
```

3. Commit and push:
```bash
git add .
git commit -m "Add Render configuration"
git push
```

### Step 2: Deploy to Render

1. Go to [render.com](https://render.com) and sign in
2. Click "New" → "Web Service"
3. Connect your GitHub repository
4. Configure:
   - **Name**: autoeia-backend
   - **Environment**: Python
   - **Build Command**: `cd platform/backend && pip install -r requirements.txt`
   - **Start Command**: `cd platform/backend && gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Instance Type**: Free (or paid for production)

5. Add environment variables if needed

6. Click "Create Web Service"

### Step 3: Update Frontend

Update your Vercel environment variable `VITE_API_URL` to point to your Render backend URL.

## Environment Variables

### Frontend (.env)

```env
VITE_API_URL=http://localhost:8000
```

Production:
```env
VITE_API_URL=https://autoeia-backend.onrender.com
```

### Backend (.env)

```env
FLASK_ENV=production
MODULES_DIR=../../modules
DATASETS_DIR=../../datasets
```

## Production Considerations

### Security

1. **CORS Configuration**: Update CORS settings in `app.py`:
```python
CORS(app, origins=['https://your-frontend-domain.vercel.app'])
```

2. **API Keys**: Add authentication if needed

3. **Rate Limiting**: Implement rate limiting for API endpoints

### Performance

1. **Frontend**:
   - Enable Vercel Edge Caching
   - Optimize bundle size
   - Use code splitting

2. **Backend**:
   - Use Render paid tier for better performance
   - Consider Redis for caching
   - Add database for workflow persistence

### Monitoring

1. **Vercel**:
   - Built-in analytics
   - Real User Monitoring (RUM)

2. **Render**:
   - Built-in metrics
   - Set up log aggregation
   - Configure alerts

### Scaling

1. **Frontend**: Automatically scales with Vercel

2. **Backend**:
   - Upgrade Render instance type
   - Consider horizontal scaling with load balancer
   - Use database for shared state

## Database Setup (Optional)

For production, consider adding PostgreSQL for:
- Workflow persistence
- User management
- Module versioning

### Render PostgreSQL

1. Create new PostgreSQL database on Render
2. Add connection string to backend environment variables
3. Update backend to use database instead of file storage

## File Storage

For production file uploads and outputs:

1. **Option 1: AWS S3**
   - Create S3 bucket
   - Add AWS credentials to backend
   - Update file handling code

2. **Option 2: Render Disks**
   - Add persistent disk to Render service
   - Mount to `/data` directory

## CI/CD Pipeline

### GitHub Actions

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: amondnet/vercel-action@v20
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
          vercel-org-id: ${{ secrets.ORG_ID}}
          vercel-project-id: ${{ secrets.PROJECT_ID}}

  deploy-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      # Render auto-deploys on push to main
```

## Health Checks

Set up health check endpoints:

1. Frontend: Vercel automatically monitors
2. Backend: Configure Render health check path: `/api/health`

## Backup Strategy

1. **Code**: Backed up in Git
2. **Workflows**: Export regularly via API
3. **Datasets**: Store in S3 with versioning
4. **Database**: Render automatic daily backups (paid plans)

## Rollback Procedure

### Vercel (Frontend)

1. Go to Deployments
2. Find previous working deployment
3. Click "Promote to Production"

### Render (Backend)

1. Go to service dashboard
2. Find previous deployment
3. Click "Rollback"

## Troubleshooting

### Frontend Issues

- Check Vercel deployment logs
- Verify environment variables
- Test API connectivity

### Backend Issues

- Check Render logs
- Verify Python dependencies
- Check module loading

### Common Problems

1. **CORS errors**: Update CORS configuration
2. **Module not found**: Check module paths and deployment
3. **Memory issues**: Upgrade instance size

## Cost Estimates

### Free Tier
- Vercel: Free (with limits)
- Render: Free (with limitations)
- Total: $0/month

### Production Tier
- Vercel Pro: $20/month
- Render Starter: $7/month
- PostgreSQL: $7/month
- Total: ~$34/month

## Support

For deployment issues:
- Vercel Support: https://vercel.com/support
- Render Support: https://render.com/docs
- GitHub Issues: Project repository
