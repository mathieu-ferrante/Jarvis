// Accès à l'API locale de Jarvis. Le jeton de l'appareil est gardé dans le stockage du navigateur
// (jamais dans l'URL des requêtes) ; il est révocable depuis le PC (SEC-13).

const CLE_JETON = "jarvis.jeton";

export function lireJeton(): string | null {
  const fragment = new URLSearchParams(location.hash.slice(1)).get("jeton");
  if (fragment) {
    try {
      localStorage.setItem(CLE_JETON, fragment);
    } catch {
      /* stockage indisponible : jeton gardé en mémoire */
    }
    history.replaceState(null, "", location.pathname);
    return fragment;
  }
  try {
    return localStorage.getItem(CLE_JETON);
  } catch {
    return null;
  }
}

export function enregistrerJeton(jeton: string | null) {
  try {
    if (jeton) localStorage.setItem(CLE_JETON, jeton);
    else localStorage.removeItem(CLE_JETON);
  } catch {
    /* ignoré */
  }
}

export class ErreurApi extends Error {
  constructor(public statut: number, message: string) {
    super(message);
  }
}

export async function api<T = any>(chemin: string, options: RequestInit = {}, jeton = lireJeton()): Promise<T> {
  const entetes: Record<string, string> = { ...(options.headers as Record<string, string>) };
  if (jeton) entetes.Authorization = `Bearer ${jeton}`;
  if (options.body && !(options.body instanceof FormData)) entetes["Content-Type"] = "application/json";
  const r = await fetch(chemin, { ...options, headers: entetes });
  if (!r.ok) {
    let message = r.statusText;
    try {
      message = (await r.json()).detail ?? message;
    } catch {
      /* corps non JSON */
    }
    throw new ErreurApi(r.status, message);
  }
  return r.json();
}

export type Evenement = { type: string; donnees: any; horodatage?: string };

/** Connexion persistante : évènements en direct et discussion. Se reconnecte seule. */
export class Connexion {
  private ws: WebSocket | null = null;
  private fermee = false;
  private delai = 1000;

  constructor(private jeton: string, private surEvenement: (e: Evenement) => void, private surEtat: (ok: boolean) => void) {
    this.ouvrir();
  }

  private ouvrir() {
    const protocole = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${protocole}://${location.host}/ws`);
    this.ws.onopen = () => {
      this.ws?.send(JSON.stringify({ jeton: this.jeton }));
      this.delai = 1000;
      this.surEtat(true);
    };
    this.ws.onmessage = (m) => this.surEvenement(JSON.parse(m.data));
    this.ws.onclose = (e) => {
      this.surEtat(false);
      if (e.code === 4401) {
        this.surEvenement({ type: "revoque", donnees: {} });
        return;
      }
      if (!this.fermee) setTimeout(() => this.ouvrir(), (this.delai = Math.min(this.delai * 2, 15000)));
    };
  }

  envoyer(message: object): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(message));
    return true;
  }

  fermer() {
    this.fermee = true;
    this.ws?.close();
  }
}
