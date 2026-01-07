# GitHub Copilot Instructions for EPG Letterboxd Alerts

## Infrastructure Management

### Bicep-First Approach
- **ALL infrastructure changes MUST be done via Bicep** (`infra/main.bicep`) whenever possible
- Only use Azure CLI/Portal for configuration that is not yet supported in Bicep/ARM
- Always update Bicep first, then deploy, rather than making manual changes in the portal

### Known Limitations
The following configurations cannot yet be managed via Bicep and require Azure CLI:

1. **Static Website Hosting** - Must be enabled via CLI after Bicep deployment:
   ```bash
   az storage blob service-properties update \
     --account-name ziggoepgletterboxd \
     --static-website \
     --index-document index.html \
     --404-document index.html \
     --auth-mode login
   ```

### Deployment Workflow
1. Make infrastructure changes in `infra/main.bicep`
2. Deploy Bicep: `az deployment group create --resource-group ziggo-epg-letterboxd-rg --template-file infra/main.bicep --parameters tmdbApiKey=<key>`
3. Apply manual configurations (if needed, see above)
4. Deploy function code: `func azure functionapp publish ziggo-epg-letterboxd-func --python --build remote`

## Python Version Management
- **Local development**: Python 3.14+ (latest)
- **Azure Functions runtime**: Python 3.12 (configured in Bicep: `linuxFxVersion: 'Python|3.12'`)
- Always verify runtime version matches Bicep after portal changes

## Azure Functions Best Practices
- Use **lazy imports** (import inside function bodies) to avoid module-level import failures during function indexing
- Wrap `load_dotenv()` in try-except to handle Azure Functions environment
- Use `DefaultAzureCredential` for all Azure SDK clients (automatic managed identity)
- Store all configuration in `config.json` in blob storage (not environment variables)

## Storage Account Architecture
- **ziggoepgletterboxd**: Data storage (RBAC-protected, firewall enabled for home IP)
  - `data` container: channels.txt, channels-series.txt, config.json, ziggogoepg_cache.sqlite3
  - `downloads` container: Letterboxd CSV exports
  - `$web` container: HTML output for static website hosting
- **ziggoepgletterboxdfunc**: Function app runtime storage (no firewall)

## Required Role Assignments
Function app managed identity needs:
- **Storage Blob Data Contributor** on ziggoepgletterboxd (read/write blobs)
- **Storage Table Data Contributor** on ziggoepgletterboxd (read/write tables)

These are defined in Bicep and applied automatically on deployment.

## Troubleshooting
- If functions disappear after Bicep deployment → Redeploy function code
- If getting 403 on storage → Verify role assignments: `az role assignment list --assignee <principalId>`
- If function indexing fails → Check for module-level import errors (use lazy imports)
