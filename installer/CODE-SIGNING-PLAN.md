# Code signing plan (researched 2026-10-12, not purchased yet)

Recommended: **Azure Artifact Signing (formerly Trusted Signing), Basic** - $9.99/month (~$120/yr, ~$360/3 yr), no hardware token, US individuals allowed.
Backup: Certum Individual Code Signing in the Cloud (SimplySign) ~EUR 117/yr.
Note: no option (EV included) removes the SmartScreen warning on day one; signing shows the verified name and builds reputation across releases. Keep ONE signing identity forever.

## Setup steps (Azure)
1. Pay-as-you-go Azure subscription, billing type Individual, legal name/address exactly as on government ID.
2. Register resource provider `Microsoft.CodeSigning`; create Artifact Signing account (Basic, East US -> endpoint https://eus.codesigning.azure.net).
3. Portal: Identity validation -> Individual -> Public (ID + selfie, a few days).
4. Create Certificate profile (Public Trust); give your login role "Artifact Signing Certificate Profile Signer".
5. Build PC: Windows SDK signtool (x64), .NET 8 runtime, NuGet Microsoft.ArtifactSigning.Client (Azure.CodeSigning.Dlib.dll), Azure CLI + `az login`.

## Build integration
metadata.json:
```json
{ "Endpoint": "https://eus.codesigning.azure.net", "CodeSigningAccountName": "<account>", "CertificateProfileName": "<profile>" }
```
Sign exe, then installer:
```powershell
signtool sign /v /fd SHA256 /tr "http://timestamp.acs.microsoft.com" /td SHA256 /dlib "C:\ArtifactSigning\bin\x64\Azure.CodeSigning.Dlib.dll" /dmdf "C:\ArtifactSigning\metadata.json" "CabinetStudio.exe"
signtool verify /pa /v "CabinetStudio.exe"
```
Inno Setup: add `SignTool=azsign` in [Setup] and compile with
`iscc "/Sazsign=<signtool path> sign /fd SHA256 /tr http://timestamp.acs.microsoft.com /td SHA256 /dlib <dlib> /dmdf <metadata.json> $f" CabinetStudio.iss`

Sources: learn.microsoft.com/azure/artifact-signing (SKU, quickstart, signing integrations); learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation; sslmentor.eu/certum/certumcodecloudindividual.
