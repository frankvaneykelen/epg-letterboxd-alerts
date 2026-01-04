// EPG Letterboxd Alerts - Azure Infrastructure
// Deploys Function App with Managed Identity and Blob Storage access

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Base name for all resources')
param projectName string = 'epg-letterboxd'

@description('Environment (dev, staging, prod)')
param environment string = 'prod'

@description('TMDb API Key')
@secure()
param tmdbApiKey string

@description('Storage account SKU')
param storageSku string = 'Standard_LRS'

// Variables
var resourceSuffix = '${projectName}-${environment}'
var dataStorageAccountName = replace('${projectName}${environment}', '-', '') // Storage accounts can't have hyphens
var funcStorageAccountName = replace('${projectName}${environment}func', '-', '') // Separate storage for Function App
var functionAppName = '${resourceSuffix}-func'
var appServicePlanName = '${resourceSuffix}-plan'
var appInsightsName = '${resourceSuffix}-ai'
var containerName = 'downloads'

// Storage Account for Function App infrastructure (no firewall - needed for deployments)
resource funcStorageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: funcStorageAccountName
  location: location
  sku: {
    name: storageSku
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
    // No firewall - allows GitHub Actions to deploy
  }
}

// Storage Account for data (Letterboxd ZIPs, static website) with IP restrictions
resource dataStorageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: dataStorageAccountName
  location: location
  sku: {
    name: storageSku
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
    // Network rules for IP restrictions on data access
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: [
        { value: '213.73.141.240' } // K202
        // Add more IPs here:
        // { value: '1.2.3.4' }
        // { value: '10.0.0.0/24' }
      ]
    }
  }
}

// Note: Static website configuration requires Azure CLI or Portal
// Run after deployment: az storage blob service-properties update --account-name epgletterboxdprod --static-website --index-document index.html

// Blob Service for data storage account
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: dataStorageAccount
  name: 'default'
  properties: {
    cors: {
      corsRules: [
        {
          allowedOrigins: [
            'https://portal.azure.com'
          ]
          allowedMethods: [
            'GET'
            'HEAD'
            'POST'
            'PUT'
            'DELETE'
            'OPTIONS'
          ]
          allowedHeaders: [
            '*'
          ]
          exposedHeaders: [
            '*'
          ]
          maxAgeInSeconds: 86400
        }
      ]
    }
  }
}

// Container for Letterboxd ZIP files
resource letterboxdContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: containerName
  properties: {
    publicAccess: 'None'
  }
}

// Container for HTML files (wwwroot)
resource wwwrootContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'wwwroot'
  properties: {
    publicAccess: 'None'  // Access controlled by storage firewall
  }
}

// Application Insights
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    Request_Source: 'rest'
  }
}

// App Service Plan (Consumption)
resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: appServicePlanName
  location: location
  kind: 'linux'
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true
  }
}

// Function App
resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    reserved: true
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${funcStorageAccount.name};EndpointSuffix=${az.environment().suffixes.storage};AccountKey=${funcStorageAccount.listKeys().keys[0].value}'
        }
        {
          name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING'
          value: 'DefaultEndpointsProtocol=https;AccountName=${funcStorageAccount.name};EndpointSuffix=${az.environment().suffixes.storage};AccountKey=${funcStorageAccount.listKeys().keys[0].value}'
        }
        {
          name: 'WEBSITE_CONTENTSHARE'
          value: toLower(functionAppName)
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'APPINSIGHTS_INSTRUMENTATIONKEY'
          value: appInsights.properties.InstrumentationKey
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'TMDB_API_KEY'
          value: tmdbApiKey
        }
      ]
    }
  }
}

// Role assignment: Storage Blob Data Contributor for Function App's Managed Identity (needs write access)
resource blobContributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  // Storage Blob Data Contributor role
  name: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
}

resource functionAppBlobAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: dataStorageAccount
  name: guid(dataStorageAccount.id, functionApp.id, blobContributorRoleDefinition.id)
  properties: {
    roleDefinitionId: blobContributorRoleDefinition.id
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Outputs
output functionAppName string = functionApp.name
output dataStorageAccountName string = dataStorageAccount.name
output funcStorageAccountName string = funcStorageAccount.name
output containerName string = containerName
output functionAppPrincipalId string = functionApp.identity.principalId
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output staticWebsiteUrl string = 'https://${dataStorageAccount.name}.z6.web.core.windows.net/'
