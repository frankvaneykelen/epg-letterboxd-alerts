// EPG Letterboxd Alerts - Azure Infrastructure
// Deploys Function App with Managed Identity and Blob Storage access

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Base name for all resources')
param projectName string = 'ziggo-epg-letterboxd'

@description('TMDb API Key')
@secure()
param tmdbApiKey string

@description('Streaming Availability API Key')
@secure()
param streamingApiKey string

@description('Storage account SKU')
param storageSku string = 'Standard_LRS'

// Variables
var resourceSuffix = projectName
var dataStorageAccountName = replace('${projectName}', '-', '') // Storage accounts can't have hyphens
var funcStorageAccountName = replace('${projectName}func', '-', '') // Separate storage for Function App
var functionAppName = '${resourceSuffix}-func'
var appServicePlanName = '${resourceSuffix}-asp'
var appInsightsName = '${resourceSuffix}-appi'
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
  tags: {
    Project: projectName
    Purpose: 'Function App Infrastructure'
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
    // Temporarily allow all to test - can restrict later once working
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'  // Allow all access for now (protected by RBAC roles)
    }
  }
  tags: {
    Project: projectName
    Purpose: 'Data Storage (Letterboxd, HTML via $web container)'
  }
}

// Note: Static website hosting must be enabled via Azure CLI (not yet supported in Bicep/ARM)
// This is documented in the deployment README and Copilot instructions

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

// $web container for static website hosting (automatically created when accessing with static website enabled)
resource webContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: '$web'
  properties: {
    publicAccess: 'None'
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

// Note: HTML files are served from the $web container, which is automatically created when static website hosting is enabled
// Run after deployment: az storage blob service-properties update --account-name ziggoepgletterboxd --static-website --index-document index.html

// Table Service for data storage account
resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2023-01-01' = {
  parent: dataStorageAccount
  name: 'default'
}

// Table for do-not-watchlist films
resource doNotWatchListTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-01-01' = {
  parent: tableService
  name: 'DoNotWatchListFilms'
}

// Table for do-not-watch series
resource doNotWatchSeriesTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-01-01' = {
  parent: tableService
  name: 'DoNotWatchListSeries'
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
  tags: {
    Project: projectName
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
  tags: {
    Project: projectName
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
      linuxFxVersion: 'Python|3.12'
      cors: {
        allowedOrigins: [
          'https://portal.azure.com'
          'https://ms.portal.azure.com'
        ]
        supportCredentials: false
      }
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
        {
          name: 'STREAMING_API_KEY'
          value: streamingApiKey
        }
        {
          name: 'STORAGE_ACCOUNT_NAME'
          value: dataStorageAccount.name
        }
        {
          name: 'STORAGE_CONTAINER_NAME'
          value: containerName
        }
        {
          name: 'AzureWebJobsFeatureFlags'
          value: 'EnableWorkerIndexing'
        }
        {
          name: 'PYTHON_ISOLATE_WORKER_DEPENDENCIES'
          value: '1'
        }
        {
          name: 'WEBSITE_RUN_FROM_PACKAGE'
          value: '1'
        }
      ]
    }
  }
  tags: {
    Project: projectName
    ManagedBy: 'Bicep'
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

// Role assignment: Storage Table Data Contributor for Function App's Managed Identity
resource tableContributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  // Storage Table Data Contributor role
  name: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
}

resource functionAppTableAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: dataStorageAccount
  name: guid(dataStorageAccount.id, functionApp.id, tableContributorRoleDefinition.id)
  properties: {
    roleDefinitionId: tableContributorRoleDefinition.id
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
output staticWebsiteUrl string = 'https://${dataStorageAccount.name}.z6.web.${az.environment().suffixes.storage}/'
