# Enable Static Website Hosting

## Update Bicep with Your IP Addresses

Edit `infra/main.bicep` and add your IP addresses to the `ipRules` array (around line 42):

```bicep
ipRules: [
  { value: 'YOUR_HOME_IP' }           // Your home IP
  { value: 'YOUR_OFFICE_IP' }         // Your office IP
  { value: '10.0.0.0/24' }            // IP range if needed
]
```

## Get Your Current IP

```powershell
(Invoke-WebRequest -Uri 'https://api.ipify.org').Content
```

## Deploy Updated Infrastructure

```powershell
cd infra
az deployment group create `
  --resource-group rg-epg-letterboxd-prod `
  --template-file main.bicep `
  --parameters main.parameters.json `
  --parameters tmdbApiKey=YOUR_TMDB_API_KEY
```

## Enable Static Website (one-time setup)

After Bicep deployment, run:

```powershell
az storage blob service-properties update `
  --account-name epgletterboxdprod `
  --static-website `
  --index-document index.html `
  --404-document index.html
```

## Update Code to Use $web Container

The static website uses the `$web` container, not `wwwroot`. Update `blob_html_writer.py`:

Change:
```python
def upload_html_to_blob(html_content: str, blob_name: str, container_name: str = "wwwroot")
```

To:
```python
def upload_html_to_blob(html_content: str, blob_name: str, container_name: str = "$web")
```

## Access Your Website

After setup, your HTML files will be accessible at:

- Films: `https://epgletterboxdprod.z6.web.core.windows.net/index.html`
- Series: `https://epgletterboxdprod.z6.web.core.windows.net/new-series.html`

(The exact URL will be shown when you enable static website)

## Security

- Only IPs in `ipRules` can access
- Storage firewall blocks all other traffic
- Function App can still access (via AzureServices bypass)
- HTTPS enforced

## Alternative: Keep Function Endpoints

If you prefer to keep the current setup with function endpoints, just add IP restrictions to the Function App instead. Let me know if you want that approach.
