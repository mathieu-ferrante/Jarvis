import { useCallback, useEffect, useRef, useState } from "react";
import { api, Connexion, enregistrerJeton, ErreurApi, Evenement, lireJeton } from "./api";

type Message = { de: "moi" | "jarvis" | "systeme"; texte: string; id: number };
type Confirmation = { id: number; question: string; outil: string; arguments: Record<string, unknown>; suite_contenu_externe: boolean };
type Onglet = "discussion" | "activite" | "memoire" | "rappels" | "tableau" | "appareils";

const ONGLETS: [Onglet, string][] = [
  ["discussion", "Discussion"],
  ["activite", "Journal"],
  ["memoire", "Mémoire"],
  ["rappels", "Rappels"],
  ["tableau", "Tableau de bord"],
  ["appareils", "Appareils"],
];

let compteur = 0;
const nouvelId = () => ++compteur;

export default function App() {
  const [jeton, setJeton] = useState<string | null>(lireJeton());
  if (!jeton) return <Appairage surJeton={(j) => { enregistrerJeton(j); setJeton(j); }} />;
  return <Principal jeton={jeton} surDeconnexion={() => { enregistrerJeton(null); setJeton(null); }} />;
}

function Appairage({ surJeton }: { surJeton: (j: string) => void }) {
  const [code, setCode] = useState("");
  const [nom, setNom] = useState(/Android/i.test(navigator.userAgent) ? "Téléphone" : /Mac/i.test(navigator.userAgent) ? "Mac" : "Navigateur");
  const [erreur, setErreur] = useState("");
  const envoyer = async (e: React.FormEvent) => {
    e.preventDefault();
    setErreur("");
    try {
      const r = await api<{ jeton: string }>("/api/appairer", { method: "POST", body: JSON.stringify({ code, nom, type: "navigateur" }) }, null);
      surJeton(r.jeton);
    } catch (err) {
      setErreur(err instanceof ErreurApi ? err.message : "Jarvis est injoignable.");
    }
  };
  return (
    <main className="appairage">
      <div className="logo" aria-hidden />
      <h1>Jarvis</h1>
      <p>Sur le PC : icône Jarvis → « Appairer un appareil… », puis saisissez le code à 6 chiffres.</p>
      <form onSubmit={envoyer}>
        <label>Code<input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required /></label>
        <label>Nom de cet appareil<input value={nom} onChange={(e) => setNom(e.target.value)} maxLength={60} /></label>
        <button disabled={code.length !== 6}>Appairer</button>
        {erreur && <p className="erreur" role="alert">{erreur}</p>}
      </form>
    </main>
  );
}

function Principal({ jeton, surDeconnexion }: { jeton: string; surDeconnexion: () => void }) {
  const [onglet, setOnglet] = useState<Onglet>("discussion");
  const [connecte, setConnecte] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [confirmations, setConfirmations] = useState<Confirmation[]>([]);
  const [etatVoix, setEtatVoix] = useState("");
  const [enCours, setEnCours] = useState(false);
  const connexion = useRef<Connexion | null>(null);

  const ajouter = useCallback((de: Message["de"], texte: string) => setMessages((m) => [...m, { de, texte, id: nouvelId() }]), []);

  const surEvenement = useCallback((e: Evenement) => {
    switch (e.type) {
      case "morceau":
        setMessages((m) => {
          const dernier = m[m.length - 1];
          if (dernier?.de === "jarvis" && dernier.id < 0) return [...m.slice(0, -1), { ...dernier, texte: dernier.texte + e.donnees.texte }];
          return [...m, { de: "jarvis", texte: e.donnees.texte, id: -nouvelId() }];
        });
        break;
      case "fin":
        setEnCours(false);
        setMessages((m) => m.map((x) => (x.id < 0 ? { ...x, id: -x.id } : x)));
        break;
      case "confirmation":
        setConfirmations((c) => [...c, e.donnees]);
        notifier("Confirmation demandée", e.donnees.question);
        break;
      case "notification":
        ajouter("systeme", `${e.donnees.titre} — ${e.donnees.texte}`);
        notifier(e.donnees.titre, e.donnees.texte);
        break;
      case "voix_transcription":
        if (e.donnees.texte) ajouter("moi", `🎙 ${e.donnees.texte}`);
        break;
      case "voix_reponse":
        if (e.donnees.texte) ajouter("jarvis", e.donnees.texte);
        break;
      case "voix_etat":
        setEtatVoix(e.donnees.etat);
        break;
      case "action":
        if (e.donnees.statut === "refusee") ajouter("systeme", `Action non exécutée : ${e.donnees.description}`);
        break;
      case "revoque":
        surDeconnexion();
        break;
    }
  }, [ajouter, surDeconnexion]);

  useEffect(() => {
    connexion.current = new Connexion(jeton, surEvenement, setConnecte);
    return () => connexion.current?.fermer();
  }, [jeton, surEvenement]);

  const envoyerTexte = (texte: string) => {
    ajouter("moi", texte);
    setEnCours(true);
    if (!connexion.current?.envoyer({ type: "texte", texte })) {
      api<{ reponse: string }>("/api/message", { method: "POST", body: JSON.stringify({ texte }) })
        .then((r) => ajouter("jarvis", r.reponse))
        .catch(() => ajouter("systeme", "Jarvis est injoignable."))
        .finally(() => setEnCours(false));
    }
  };

  const repondre = async (c: Confirmation, oui: boolean) => {
    setConfirmations((l) => l.filter((x) => x.id !== c.id));
    try {
      await api(`/api/confirmation/${c.id}`, { method: "POST", body: JSON.stringify({ oui }) });
    } catch {
      ajouter("systeme", "Confirmation expirée.");
    }
  };

  return (
    <div className="app">
      <header>
        <div className={`pastille ${connecte ? "ok" : ""}`} title={connecte ? "Connecté" : "Déconnecté"} />
        <strong>Jarvis</strong>
        {etatVoix && <span className="etat">{libelleEtat(etatVoix)}</span>}
        <button className="arret" onClick={() => connexion.current?.envoyer({ type: "arret" }) || api("/api/arret", { method: "POST" })} title="Arrêt d'urgence">■ Stop</button>
      </header>
      <nav>
        {ONGLETS.map(([cle, libelle]) => (
          <button key={cle} className={onglet === cle ? "actif" : ""} onClick={() => setOnglet(cle)}>{libelle}</button>
        ))}
      </nav>
      <main>
        {onglet === "discussion" && <Discussion messages={messages} enCours={enCours} surTexte={envoyerTexte} surAudio={(t, r) => { ajouter("moi", `🎙 ${t}`); ajouter("jarvis", r); }} />}
        {onglet === "activite" && <Journal />}
        {onglet === "memoire" && <Memoire />}
        {onglet === "rappels" && <Rappels />}
        {onglet === "tableau" && <Tableau />}
        {onglet === "appareils" && <Appareils surDeconnexion={surDeconnexion} />}
      </main>
      {confirmations.map((c) => (
        <div className="modale" role="dialog" aria-modal key={c.id}>
          <div className="boite">
            <h2>Confirmer ?</h2>
            <p>{c.question}</p>
            {c.suite_contenu_externe && <p className="alerte">⚠ Proposée à la suite d'un contenu lu (mail, page, message), pas d'une demande directe.</p>}
            <pre>{JSON.stringify(c.arguments, null, 2)}</pre>
            <div className="boutons">
              <button className="non" onClick={() => repondre(c, false)}>Non</button>
              <button className="oui" onClick={() => repondre(c, true)}>Oui, exécuter</button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function libelleEtat(e: string) {
  return ({ veille: "en veille", ecoute: "écoute…", suite: "écoute…", reflexion: "réfléchit…", parole: "parle", confirmation: "attend ta réponse" } as Record<string, string>)[e] ?? e;
}

function notifier(titre: string, texte: string) {
  if (document.visibilityState === "visible" || !("Notification" in window) || Notification.permission !== "granted") return;
  navigator.serviceWorker?.ready.then((r) => r.showNotification(titre, { body: texte, icon: "/icone-192.png", tag: titre })).catch(() => undefined);
}

function Discussion({ messages, enCours, surTexte, surAudio }: { messages: Message[]; enCours: boolean; surTexte: (t: string) => void; surAudio: (t: string, r: string) => void }) {
  const [texte, setTexte] = useState("");
  const [enregistre, setEnregistre] = useState(false);
  const [envoi, setEnvoi] = useState(false);
  const fin = useRef<HTMLDivElement>(null);
  const enregistreur = useRef<MediaRecorder | null>(null);
  const morceaux = useRef<Blob[]>([]);

  useEffect(() => {
    fin.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const commencer = async () => {
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    try {
      const flux = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
      const type = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
      const r = new MediaRecorder(flux, type ? { mimeType: type, audioBitsPerSecond: 24000 } : undefined);
      morceaux.current = [];
      r.ondataavailable = (e) => morceaux.current.push(e.data);
      r.onstop = async () => {
        flux.getTracks().forEach((t) => t.stop());
        const corps = new FormData();
        corps.append("fichier", new Blob(morceaux.current, { type: r.mimeType }), "parole.webm");
        setEnvoi(true);
        try {
          const res = await api<{ transcription: string; reponse: string; audio_wav_b64?: string }>("/api/audio", { method: "POST", body: corps });
          surAudio(res.transcription || "(rien entendu)", res.reponse);
          if (res.audio_wav_b64) new Audio(`data:audio/wav;base64,${res.audio_wav_b64}`).play().catch(() => undefined);
        } catch {
          surAudio("(erreur)", "Jarvis est injoignable.");
        } finally {
          setEnvoi(false);
        }
      };
      r.start();
      enregistreur.current = r;
      setEnregistre(true);
    } catch {
      alert("Micro indisponible : l'interface doit être ouverte en HTTPS (tailscale serve) et le micro autorisé.");
    }
  };
  const arreter = () => {
    enregistreur.current?.stop();
    setEnregistre(false);
  };

  return (
    <section className="discussion">
      <div className="fil" aria-live="polite">
        {messages.length === 0 && <p className="vide">Dis « Jarvis » au PC, ou écris ici.</p>}
        {messages.map((m) => <div key={m.id} className={`bulle ${m.de}`}>{m.texte}</div>)}
        {(enCours || envoi) && <div className="bulle jarvis attente">…</div>}
        <div ref={fin} />
      </div>
      <form className="saisie" onSubmit={(e) => { e.preventDefault(); if (texte.trim()) { surTexte(texte.trim()); setTexte(""); } }}>
        <button type="button" className={`micro ${enregistre ? "actif" : ""}`} onPointerDown={commencer} onPointerUp={arreter} onPointerLeave={() => enregistre && arreter()} aria-label="Maintenir pour parler">🎙</button>
        <input value={texte} onChange={(e) => setTexte(e.target.value)} placeholder="Écrire à Jarvis…" enterKeyHint="send" />
        <button disabled={!texte.trim()}>Envoyer</button>
      </form>
    </section>
  );
}

function useDonnees<T>(chemin: string, intervalle = 0): [T | null, () => void, string] {
  const [donnees, setDonnees] = useState<T | null>(null);
  const [erreur, setErreur] = useState("");
  const charger = useCallback(() => {
    api<T>(chemin).then((d) => { setDonnees(d); setErreur(""); }).catch((e) => setErreur(String(e.message ?? e)));
  }, [chemin]);
  useEffect(() => {
    charger();
    if (!intervalle) return;
    const t = setInterval(charger, intervalle);
    return () => clearInterval(t);
  }, [charger, intervalle]);
  return [donnees, charger, erreur];
}

function Journal() {
  const [d, recharger, erreur] = useDonnees<{ actions: any[] }>("/api/journal?n=200", 10000);
  return (
    <section>
      <div className="entete-section"><h2>Journal des actions</h2><button onClick={recharger}>Actualiser</button></div>
      {erreur && <p className="erreur">{erreur}</p>}
      <ul className="liste">
        {d?.actions.map((a) => (
          <li key={a.id} className={a.ok ? "" : "echec"}>
            <div><strong>{a.outil}</strong> <span className={`badge ${a.niveau}`}>{a.niveau}</span> <span className="badge">{a.decision}</span>{a.suite_contenu_externe ? <span className="badge alerte">après contenu lu</span> : null}</div>
            <small>{a.horodatage.replace("T", " ")} — {a.origine} — « {a.demande} »</small>
            <code>{a.arguments}</code>
            <small>{a.resultat}</small>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Memoire() {
  const [q, setQ] = useState("");
  const [d, recharger] = useDonnees<{ faits: any[]; statistiques: Record<string, number> }>(`/api/memoire?q=${encodeURIComponent(q)}`);
  const oublier = async (id: number) => {
    if (!confirm("Oublier définitivement ce souvenir ?")) return;
    await api(`/api/memoire/${id}`, { method: "DELETE" });
    recharger();
  };
  const corriger = async (id: number, ancien: string) => {
    const texte = prompt("Corriger le souvenir :", ancien);
    if (texte && texte !== ancien) {
      await api(`/api/memoire/${id}`, { method: "PUT", body: JSON.stringify({ texte }) });
      recharger();
    }
  };
  return (
    <section>
      <div className="entete-section"><h2>Ce que Jarvis sait</h2>{d && <small>{d.statistiques.faits} souvenirs · {d.statistiques.echanges} échanges · {d.statistiques.documents} passages indexés</small>}</div>
      <input className="recherche" placeholder="Chercher un sujet…" value={q} onChange={(e) => setQ(e.target.value)} />
      <ul className="liste">
        {d?.faits.map((f) => (
          <li key={f.id}>
            <div>{f.texte}</div>
            <small>n° {f.id} · {f.modifie?.slice(0, 10)} · {f.source}</small>
            <div className="actions"><button onClick={() => corriger(f.id, f.texte)}>Corriger</button><button className="non" onClick={() => oublier(f.id)}>Oublier</button></div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Rappels() {
  const [d] = useDonnees<{ rappels: any[]; taches: any[] }>("/api/rappels", 15000);
  return (
    <section>
      <h2>Rappels et minuteurs</h2>
      <ul className="liste">{d?.rappels.map((r) => <li key={r.id}><strong>{r.texte}</strong><small>{r.quand.replace("T", " ")} · {r.type}{r.recurrence !== "aucune" ? ` · ${r.recurrence}` : ""}</small></li>)}</ul>
      {d?.rappels.length === 0 && <p className="vide">Aucun rappel.</p>}
      <h2>Tâches de fond</h2>
      <ul className="liste">{d?.taches.map((t) => <li key={t.id}><strong>{t.objectif}</strong><small>{t.etat} · {t.debut}</small><small>{t.resultat}</small></li>)}</ul>
    </section>
  );
}

function Tableau() {
  const [d] = useDonnees<any>("/api/etat", 3000);
  if (!d) return <p className="vide">Chargement…</p>;
  const voix = d.echanges.filter((e: any) => e.latence_ms);
  const moyenne = voix.length ? Math.round(voix.reduce((s: number, e: any) => s + e.latence_ms, 0) / voix.length) : null;
  return (
    <section>
      <h2>Tableau de bord</h2>
      <div className="tuiles">
        <Tuile titre="Modèle" valeur={d.pret ? d.modele : "chargement…"} />
        <Tuile titre="Démarrage" valeur={d.demarrage_s ? `${d.demarrage_s} s` : "—"} cible="< 15 s" />
        <Tuile titre="Latence voix moyenne" valeur={moyenne ? `${moyenne} ms` : "—"} cible="< 1 000 ms" alerte={!!moyenne && moyenne > 1500} />
        <Tuile titre="CPU" valeur={`${Math.round(d.cpu_pct)} %`} />
        <Tuile titre="GPU" valeur={d.gpu?.charge_3d_pct != null ? `${d.gpu.charge_3d_pct} % · ${d.gpu.vram_go} Go` : "—"} />
        <Tuile titre="Mode" valeur={d.en_jeu?.en_jeu ? `jeu (${d.en_jeu.jeu})` : "normal"} />
      </div>
      <h3>Derniers échanges</h3>
      <table>
        <thead><tr><th>Canal</th><th>Demande</th><th>Transcription</th><th>Modèle</th><th>Voix</th><th>Total</th></tr></thead>
        <tbody>
          {d.echanges.slice().reverse().map((e: any, i: number) => (
            <tr key={i}><td>{e.canal}</td><td>{e.texte}</td><td>{e.transcription_ms ?? "—"}</td><td>{e.premier_texte_ms ?? "—"}</td><td>{e.voix_ms ?? "—"}</td><td className={(e.latence_ms ?? 0) > 1500 ? "alerte" : ""}>{e.latence_ms ?? e.total_ms} ms</td></tr>
          ))}
        </tbody>
      </table>
      {d.refus_reseau?.length > 0 && <><h3>Sorties réseau bloquées (SEC-04)</h3><ul className="liste">{d.refus_reseau.map((r: any, i: number) => <li key={i}>{r.hote} — {r.outil ?? "cœur"} — {r.motif}</li>)}</ul></>}
    </section>
  );
}

function Tuile({ titre, valeur, cible, alerte }: { titre: string; valeur: string; cible?: string; alerte?: boolean }) {
  return <div className={`tuile ${alerte ? "alerte" : ""}`}><small>{titre}</small><strong>{valeur}</strong>{cible && <small>objectif {cible}</small>}</div>;
}

function Appareils({ surDeconnexion }: { surDeconnexion: () => void }) {
  const [d, recharger] = useDonnees<{ appareils: any[]; actif: string | null; moi: string }>("/api/appareils");
  const [code, setCode] = useState("");
  const revoquer = async (id: string, nom: string) => {
    if (!confirm(`Révoquer ${nom} ? Il devra être appairé à nouveau.`)) return;
    await api(`/api/appareils/${id}`, { method: "DELETE" });
    if (id === d?.moi) surDeconnexion();
    recharger();
  };
  return (
    <section>
      <h2>Appareils appairés</h2>
      {d?.moi === "pc" && <p><button onClick={async () => setCode((await api<{ code: string }>("/api/appareils/code", { method: "POST" })).code)}>Générer un code d'appairage</button> {code && <strong className="code">{code}</strong>}</p>}
      <ul className="liste">
        {d?.appareils.map((a) => (
          <li key={a.id}>
            <strong>{a.nom}</strong> {a.id === d.actif && <span className="badge">actif</span>} {a.id === d.moi && <span className="badge">cet appareil</span>}
            <small>{a.type} · appairé le {a.appaire?.slice(0, 10)}</small>
            <div className="actions"><button className="non" onClick={() => revoquer(a.id, a.nom)}>Révoquer</button></div>
          </li>
        ))}
      </ul>
      {d?.moi !== "pc" && <button onClick={surDeconnexion}>Se déconnecter de cet appareil</button>}
    </section>
  );
}
