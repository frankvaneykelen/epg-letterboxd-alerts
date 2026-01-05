# Azure Infrastructure Deployment

This folder contains the Infrastructure as Code (IaC) for deploying the EPG Letterboxd Alerts Function App to Azure.

## Prerequisites

- Azure CLI installed: `az --version`
- Logged in to Azure: `az login`
- Active Azure subscription

## Resources Created

- **Function App** (Python 3.11, Consumption Plan)
- **Storage Account** (for function app and Letterboxd ZIPs)
- **Application Insights** (monitoring and logs)
- **Blob Container** (`downloads` for Letterboxd exports)
- **Managed Identity** (system-assigned, with Storage Blob Data Reader role)

## Deployment Steps

### 1. Create Resource Group

```bash
az group create \
  --name rg-epg-letterboxd-prod \
  --location westeurope
```

### 2. Deploy Infrastructure

**Option A: Using parameters file**

Edit `main.parameters.json` with your TMDb API key, then deploy:

```bash
az deployment group create \
  --resource-group rg-epg-letterboxd-prod \
  --template-file infra/main.bicep \
  --parameters infra/main.parameters.json \
  --parameters tmdbApiKey=YOUR_TMDB_API_KEY
```

**Option B: Inline parameters**

```bash
az deployment group create \
  --resource-group rg-epg-letterboxd-prod \
  --template-file infra/main.bicep \
  --parameters projectName=epg-letterboxd \
               environment=prod \
               location=westeurope \
               tmdbApiKey=YOUR_TMDB_API_KEY
```

### 3. Upload Letterboxd ZIP

After deployment, upload your Letterboxd export ZIP to the blob storage:

```bash
# Get storage account name from deployment output
STORAGE_ACCOUNT=$(az deployment group show \
  --resource-group rg-epg-letterboxd-prod \
  --name main \
  --query properties.outputs.storageAccountName.value -o tsv)

# Upload ZIP file
az storage blob upload \
  --account-name $STORAGE_ACCOUNT \
  --container-name downloads \
  --name letterboxd-stereoparty-2026-01-03-18-26-utc.zip \
  --file ~/Downloads/letterboxd-stereoparty-2026-01-03-18-26-utc.zip \
  --auth-mode login
```

### 4. Deploy Function Code

Use GitHub Actions (see `.github/workflows/deploy.yml`) or deploy manually:

```bash
# Get function app name
FUNCTION_APP=$(az deployment group show \
  --resource-group rg-epg-letterboxd-prod \
  --name main \
  --query properties.outputs.functionAppName.value -o tsv)

# Deploy using Azure Functions Core Tools
func azure functionapp publish $FUNCTION_APP
```

Or set up GitHub Actions with these secrets:
- `AZURE_FUNCTION_APP_NAME`: Output from deployment
- `AZURE_FUNCTION_PUBLISH_PROFILE`: Download from Azure Portal

## Configuration

### Update TMDb API Key

```bash
az functionapp config appsettings set --resource-group rg-epg-letterboxd-prod --name epg-letterboxd-prod-func --settings "TMDB_API_KEY=your_new_key"
```

### View Logs

```bash
az functionapp log tail \
  --resource-group rg-epg-letterboxd-prod \
  --name epg-letterboxd-prod-func
```

Or use Application Insights in Azure Portal.

## Cleanup

```bash
az group delete --name rg-epg-letterboxd-prod --yes --no-wait
```

## Parameters Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `projectName` | Base name for resources | `epg-letterboxd` |
| `environment` | Environment suffix | `prod` |
| `location` | Azure region | Resource group location |
| `tmdbApiKey` | TMDb API key (secure) | Required |
| `storageSku` | Storage account SKU | `Standard_LRS` |

## Managed Identity

The Function App uses **System-assigned Managed Identity** with **Storage Blob Data Reader** role on the storage account. This allows the function to:
- Download Letterboxd ZIPs from blob storage
- No connection strings or secrets needed

The import script (`import_letterboxd.py`) uses `DefaultAzureCredential` which automatically uses the Managed Identity in Azure.
