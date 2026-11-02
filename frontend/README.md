# md-travel-planner — frontend

React + TypeScript + Vite, Tailwind CSS v4 and shadcn/ui (`src/components/ui/`, added with
`npx shadcn@latest add <name>`). Setup, env vars and run modes: [../docs/setup-guide.md](../docs/setup-guide.md).

```bash
npm install
cp .env.example .env.local   # PowerShell: copy .env.example .env.local
npm run dev                  # http://localhost:5173 (start the backend too)
npm run lint                 # ESLint
npm run format               # Prettier (write); format:check to verify only
npm run build                # type-check + production build
```

`@/` is an alias for `src/` (configured in `tsconfig.json`, `tsconfig.app.json` and `vite.config.ts`).
