# Biluppgifter API-assistent

En enkel webbapp där besökare kan ställa frågor om Biluppgifters API.
Svaren baseras uteslutande på https://data.biluppgifter.se/.

## Deploy till Vercel (5 minuter)

### 1. Installera Vercel CLI
```bash
npm install -g vercel
```

### 2. Logga in
```bash
vercel login
```

### 3. Deploya
```bash
cd biluppgifter-agent
vercel --prod
```

### 4. Lägg till API-nyckel
Gå till **Vercel Dashboard → ditt projekt → Settings → Environment Variables** och lägg till:

| Namn                | Värde           |
|---------------------|-----------------|
| `ANTHROPIC_API_KEY` | `sk-ant-api…`   |

Hämta din nyckel på https://console.anthropic.com

### 5. Redeploya (för att variabeln ska gälla)
```bash
vercel --prod
```

## Projektstruktur

```
biluppgifter-agent/
├── api/
│   └── ask.py          # Python serverless function (håller API-nyckeln)
├── public/
│   └── index.html      # Frontend
└── vercel.json         # Routing-konfiguration
```

## Hur det fungerar

1. Besökaren skriver en fråga, väljer ton (Tekniskt/Nyfiket) och om källreferenser ska inkluderas.
2. Webbläsaren skickar frågan till `/api/ask` (Python-funktionen på Vercel).
3. Servern hämtar dokumentationen från `data.biluppgifter.se`, bygger en systemprompt och anropar Anthropic API.
4. Svaret returneras till webbläsaren och renderas som markdown.

API-nyckeln är aldrig synlig för besökaren.
