"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, Bot, Building2, Copy, ExternalLink, Globe2, ImagePlus, Inbox, LoaderCircle, MessageCircle, QrCode, Radio, Save, Settings2, ShieldAlert, ShieldCheck, Star, Trash2, UserRound } from "lucide-react";
import { EmptyState, StatusBadge } from "@/components/ui";
import { FormSkeleton, ListRowsSkeleton } from "@/components/skeleton";
import { useToast } from "@/components/toast";
import { api, messageFrom } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { AgentSummary, Client, ClientDomain, Conversation, Department, InvitationOut, PortalUser } from "@/types";

type Tab = "details" | "agents" | "channels" | "departments" | "inbox" | "portal";

export default function ClientDetailPage() {
  const t = useT();
  const toast = useToast();
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [client, setClient] = useState<Client | null>(null);
  const [tab, setTab] = useState<Tab>("details");
  const [busy, setBusy] = useState(false);
  const [logoVersion, setLogoVersion] = useState(0);
  const logoRef = useRef<HTMLInputElement>(null);
  const load = () => api<Client>(`/clients/${id}`).then(setClient);
  useEffect(() => { load(); }, [id]);

  async function uploadLogo(file?: File) {
    if (!file) return;
    setBusy(true);
    const data = new FormData(); data.append("file", file);
    try { setClient(await api<Client>(`/clients/${id}/logo`, { method: "POST", body: data })); setLogoVersion((v) => v + 1); toast.success(t("clients.detail.logoUpdated")); }
    catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); if (logoRef.current) logoRef.current.value = ""; }
  }
  async function deleteLogo() {
    await api(`/clients/${id}/logo`, { method: "DELETE" }); setLogoVersion((v) => v + 1); await load();
  }

  async function saveDetails(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true);
    const data = new FormData(event.currentTarget);
    try { setClient(await api<Client>(`/clients/${id}`, { method: "PATCH", body: JSON.stringify({ name: data.get("name"), industry: data.get("industry"), description: data.get("description"), general_context: data.get("general_context"), is_active: data.get("is_active") === "on" }) })); toast.success(t("clients.detail.detailsSaved")); }
    catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }

  async function savePortal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true);
    const data = new FormData(event.currentTarget);
    const payload: Record<string, unknown> = { portal_enabled: data.get("portal_enabled") === "on", portal_slug: data.get("portal_slug"), portal_title: data.get("portal_title") };
    try { setClient(await api<Client>(`/clients/${id}/portal`, { method: "PATCH", body: JSON.stringify(payload) })); toast.success(t("clients.detail.portalUpdated")); }
    catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }

  async function remove() {
    if (!client || !confirm(t("clients.detail.confirmDelete", { name: client.name }))) return;
    await api(`/clients/${id}`, { method: "DELETE" }); router.push("/clients");
  }

  if (!client) return <div className="page"><FormSkeleton sections={2} /></div>;
  const portalUrl = `${typeof window === "undefined" ? "http://localhost:3000" : window.location.origin}/portal/${client.portal_slug}`;
  return <div className="page">
    <Link href="/clients" className="back-link"><ArrowLeft size={17} /> {t("clients.detail.back")}</Link>
    <header className="entity-header"><div className="entity-avatar xl">{client.name.slice(0, 2).toUpperCase()}</div><div><div className="title-line"><h1>{client.name}</h1><StatusBadge active={client.is_active} /></div><p>{client.industry || t("clients.detail.industryUndefined")} · {client.agents.length === 1 ? t("clients.detail.agentOne", { count: client.agents.length }) : t("clients.detail.agentMany", { count: client.agents.length })}</p></div><div className="header-actions"><Link href={`/agents/new?client=${client.id}`} className="button primary"><Bot size={17} /> {t("clients.detail.newAgent")}</Link></div></header>
    <nav className="tabs client-tabs"><button className={tab === "details" ? "active" : ""} onClick={() => setTab("details")}><Settings2 size={17} /> {t("clients.detail.tabDetails")}</button><button className={tab === "agents" ? "active" : ""} onClick={() => setTab("agents")}><Bot size={17} /> {t("clients.detail.tabAgents")} <span>{client.agents.length}</span></button><button className={tab === "channels" ? "active" : ""} onClick={() => setTab("channels")}><Radio size={17} /> {t("clients.detail.tabChannels")}</button><button className={tab === "departments" ? "active" : ""} onClick={() => setTab("departments")}><Building2 size={17} /> {t("clients.detail.tabDepartments")}</button><button className={tab === "inbox" ? "active" : ""} onClick={() => setTab("inbox")}><Inbox size={17} /> {t("clients.detail.tabInbox")}</button><button className={tab === "portal" ? "active" : ""} onClick={() => setTab("portal")}><Globe2 size={17} /> {t("clients.detail.tabPortal")}</button></nav>

    {tab === "details" && <form className="page-form" onSubmit={saveDetails}><section className="form-section"><div className="section-copy"><h2>{t("clients.detail.clientInfo")}</h2><p>{t("clients.detail.clientInfoCopy")}</p></div><div className="form-fields"><div className="logo-editor"><button type="button" className="logo-preview" onClick={() => logoRef.current?.click()}>{client.logo_url ? <img src={`${client.logo_url}&r=${logoVersion}`} alt={t("clients.detail.logoAlt")} /> : <ImagePlus size={24} />}</button><div><strong>{t("clients.detail.logoLabel")}</strong><small>{t("clients.detail.logoHint")}</small><div><button type="button" className="text-button" onClick={() => logoRef.current?.click()}>{t("clients.detail.logoChange")}</button>{client.logo_url && <button type="button" className="text-button danger-text" onClick={deleteLogo}><Trash2 size={14} /> {t("clients.detail.logoRemove")}</button>}</div></div><input ref={logoRef} hidden type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" onChange={(e) => uploadLogo(e.target.files?.[0])} /></div><div className="form-grid"><label>{t("clients.detail.name")}<input name="name" required defaultValue={client.name} /></label><label>{t("clients.detail.industry")}<input name="industry" defaultValue={client.industry} /></label></div><label>{t("clients.detail.descriptionLabel")}<textarea name="description" rows={3} defaultValue={client.description} /></label><label>{t("clients.detail.generalContext")}<textarea name="general_context" rows={9} defaultValue={client.general_context} /><span className="field-help">{t("clients.detail.generalContextHelp")}</span></label><label className="switch-row"><span><strong>{t("clients.detail.activeClient")}</strong><small>{t("clients.detail.activeClientHint")}</small></span><input name="is_active" type="checkbox" defaultChecked={client.is_active} /></label></div></section><div className="form-footer split"><button type="button" className="button danger" onClick={remove}><Trash2 size={16} /> {t("clients.detail.deleteClient")}</button><button className="button primary" disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />} {t("clients.detail.saveChanges")}</button></div></form>}

    {tab === "agents" && (client.agents.length ? <div className="table-shell"><table className="data-table"><thead><tr><th>{t("clients.detail.colAgent")}</th><th>{t("clients.detail.colFunction")}</th><th>{t("clients.detail.colStatus")}</th><th /></tr></thead><tbody>{client.agents.map((agent) => <tr key={agent.id}><td><Link className="entity-cell" href={`/agents/${agent.id}`}><span className="agent-avatar"><Bot size={18} /></span><strong>{agent.name}</strong></Link></td><td>{agent.description || t("clients.detail.noDescription")}</td><td><StatusBadge active={agent.is_active} /></td><td><Link className="row-arrow" href={`/agents/${agent.id}`}><ArrowRight size={17} /></Link></td></tr>)}</tbody></table></div> : <EmptyState icon={<Bot />} title={t("clients.detail.agentsEmptyTitle")} description={t("clients.detail.agentsEmptyDescription")} action={<Link href={`/agents/new?client=${client.id}`} className="button primary">{t("clients.detail.createAgent")}</Link>} />)}

    {tab === "channels" && <section className="compact-channel-grid"><article className="channel-live"><span><MessageCircle size={20} /></span><div><strong>{t("channels.whatsappCloud.title")}</strong><small>{t("clients.detail.channelWhatsappAvailable", { name: client.name })}</small></div><Link className="button secondary" href={`/clients/${client.id}/channels/whatsapp-cloud`}>{t("clients.detail.configure")}</Link></article><article className="channel-live"><span><QrCode size={20} /></span><div><strong>{t("channels.whatsapp.title")}</strong><small>{t("clients.detail.channelWhatsappQrAvailable")}</small></div><Link className="button secondary" href={`/clients/${client.id}/channels/whatsapp`}>{t("clients.detail.configure")}</Link></article><article className="channel-live"><span><Globe2 size={20} /></span><div><strong>{t("channels.webchat.title")}</strong><small>{t("clients.detail.channelWebchatAvailable")}</small></div>{client.agents.length ? <Link className="button secondary" href={`/agents/${client.agents[0].id}?tab=widget`}>{t("clients.detail.configure")}</Link> : <button disabled>{t("clients.detail.connect")}</button>}</article>{["Instagram", "Facebook Messenger"].map((name) => <article key={name}><span><MessageCircle size={20} /></span><div><strong>{name}</strong><small>{t("clients.detail.comingSoon")}</small></div><button disabled>{t("clients.detail.connect")}</button></article>)}</section>}

    {tab === "departments" && <Departments clientId={client.id} agents={client.agents} />}

    {tab === "inbox" && <ClientInbox clientId={client.id} />}

    {tab === "portal" && <><form className="page-form" onSubmit={savePortal}><section className="form-section"><div className="section-copy"><h2>{t("clients.detail.portalTitle")}</h2><p>{t("clients.detail.portalCopy")}</p></div><div className="form-fields"><label>{t("clients.detail.portalTitleLabel")}<input name="portal_title" defaultValue={client.portal_title} placeholder={t("clients.detail.portalTitlePlaceholder", { name: client.name })} /></label><label>{t("clients.detail.portalUrl")}<div className="slug-input"><span>localhost:3000/portal/</span><input name="portal_slug" defaultValue={client.portal_slug} /></div></label><div className="url-preview"><code>{portalUrl}</code><button type="button" onClick={() => navigator.clipboard.writeText(portalUrl)}><Copy size={15} /> {t("clients.detail.copy")}</button>{client.portal_enabled && <a href={portalUrl} target="_blank"><ExternalLink size={15} /> {t("clients.detail.open")}</a>}</div><label className="switch-row"><span><strong>{t("clients.detail.publishPortal")}</strong><small>{t("clients.detail.publishPortalHint")}</small></span><input name="portal_enabled" type="checkbox" defaultChecked={client.portal_enabled} /></label></div></section><div className="form-footer"><button className="button primary" disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />} {t("clients.detail.savePortal")}</button></div></form><PortalUsers clientId={client.id} /><PortalDomain clientId={client.id} /></>}
  </div>;
}

function Departments({ clientId, agents }: { clientId: string; agents: AgentSummary[] }) {
  const t = useT();
  const toast = useToast();
  const [rows, setRows] = useState<Department[] | null>(null);
  const [busy, setBusy] = useState(false);
  // Solo dura hasta el próximo alta: es el único momento en que el token en
  // claro existe (Spec: Optional Invitation On Department Creation), y
  // `list_departments` no lo repite en una lectura posterior.
  const [lastInvitation, setLastInvitation] = useState<InvitationOut | null>(null);

  const load = useCallback(async () => {
    setRows(await api<Department[]>(`/clients/${clientId}/departments`));
  }, [clientId]);
  useEffect(() => { load().catch(() => {}); }, [load]);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const inviteEmail = String(data.get("invite_email") ?? "").trim();
    setBusy(true);
    setLastInvitation(null);
    try {
      const created = await api<Department>(`/clients/${clientId}/departments`, {
        method: "POST",
        body: JSON.stringify({
          name: data.get("name"),
          agent_id: data.get("agent_id"),
          description: data.get("description"),
          position: (rows?.length ?? 0),
          invite_email: inviteEmail || undefined,
        }),
      });
      form.reset();
      if (created.invitation) {
        toast.success(created.invitation.delivery === "manual" ? t("clients.detail.departmentInviteManual") : t("clients.detail.departmentInviteSent"));
        setLastInvitation(created.invitation);
      } else {
        toast.success(t("clients.detail.departmentAdded"));
      }
      await load();
    } catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }

  async function patch(row: Department, body: Record<string, unknown>) {
    try { await api(`/clients/${clientId}/departments/${row.id}`, { method: "PATCH", body: JSON.stringify(body) }); toast.success(t("clients.detail.departmentSaved")); await load(); }
    catch (err) { toast.error(messageFrom(err)); }
  }

  async function remove(row: Department) {
    if (!confirm(t("clients.detail.departmentConfirmDelete", { name: row.name }))) return;
    try { await api(`/clients/${clientId}/departments/${row.id}`, { method: "DELETE" }); toast.success(t("clients.detail.departmentRemoved")); await load(); }
    catch (err) { toast.error(messageFrom(err)); }
  }

  if (!agents.length) return <EmptyState icon={<Building2 />} title={t("clients.detail.departmentsTitle")} description={t("clients.detail.departmentsNeedAgent")} action={<Link href={`/agents/new?client=${clientId}`} className="button primary">{t("clients.detail.createAgent")}</Link>} />;

  const inMenu = (rows ?? []).filter((row) => row.enabled);
  return <section className="form-section"><div className="section-copy"><h2>{t("clients.detail.departmentsTitle")}</h2><p>{t("clients.detail.departmentsCopy")}</p></div><div className="form-fields">
    {rows === null ? <ListRowsSkeleton rows={3} /> : rows.length ? <div className="table-shell"><table className="data-table"><thead><tr><th>{t("clients.detail.departmentName")}</th><th>{t("clients.detail.departmentAgent")}</th><th>{t("clients.detail.departmentColMenu")}</th><th /><th /></tr></thead><tbody>
      {rows.map((row) => <tr key={row.id}>
        <td><span className="entity-cell"><span className="agent-avatar"><Building2 size={17} /></span><span><strong>{row.name}</strong>{row.is_entry && <small style={{ display: "block", color: "#89909d" }}><Star size={11} /> {t("clients.detail.departmentEntry")}</small>}</span></span></td>
        <td>{row.agent_name ?? "—"}</td>
        <td><StatusBadge active={row.enabled} /></td>
        <td>{!row.is_entry && <button type="button" className="text-button" onClick={() => patch(row, { is_entry: true })}>{t("clients.detail.departmentMakeEntry")}</button>}</td>
        <td>
          <button type="button" className="text-button" onClick={() => patch(row, { enabled: !row.enabled })}>{row.enabled ? t("clients.detail.departmentDisable") : t("clients.detail.departmentEnable")}</button>
          {!row.is_entry && <button type="button" className="text-button danger-text" onClick={() => remove(row)} aria-label={t("clients.detail.portalUserRemove")}><Trash2 size={15} /></button>}
        </td>
      </tr>)}
    </tbody></table></div> : <p className="field-help">{t("clients.detail.departmentsEmpty")}</p>}

    {inMenu.length > 0 && <div className="field-help">
      <strong>{t("clients.detail.departmentPreviewTitle")}</strong>{" "}
      {inMenu.length <= 3 ? t("clients.detail.departmentPreviewButtons") : t("clients.detail.departmentPreviewList")}{" "}
      {t("clients.detail.departmentPreviewQr")}
    </div>}

    <form onSubmit={add} className="form-fields">
      <div className="form-grid">
        <label>{t("clients.detail.departmentName")}<input name="name" required minLength={2} maxLength={120} /></label>
        <label>{t("clients.detail.departmentAgent")}<select name="agent_id" required>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
      </div>
      <label>{t("clients.detail.departmentDescription")}<input name="description" maxLength={72} /><span className="field-help">{t("clients.detail.departmentDescriptionHelp")}</span></label>
      <label>{t("clients.detail.departmentInviteEmail")}<input name="invite_email" type="email" placeholder={t("clients.detail.departmentInviteEmailPlaceholder")} /><span className="field-help">{t("clients.detail.departmentInviteEmailHelp")}</span></label>
      <button className="button secondary align-start" disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Building2 size={15} />} {t("clients.detail.departmentAdd")}</button>
    </form>

    {lastInvitation?.accept_url && <div className="field-help">
      <strong>{t("clients.detail.departmentInviteLinkTitle")}</strong>
      <div className="url-preview"><code>{lastInvitation.accept_url}</code><button type="button" onClick={() => navigator.clipboard.writeText(lastInvitation.accept_url!)}><Copy size={15} /> {t("clients.detail.copy")}</button></div>
    </div>}
  </div></section>;
}

function PortalUsers({ clientId }: { clientId: string }) {
  const t = useT();
  const toast = useToast();
  const [users, setUsers] = useState<PortalUser[] | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setUsers(await api<PortalUser[]>(`/clients/${clientId}/portal-users`));
  }, [clientId]);
  useEffect(() => { load().catch(() => {}); }, [load]);
  useEffect(() => { api<Department[]>(`/clients/${clientId}/departments`).then(setDepartments).catch(() => {}); }, [clientId]);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const department = data.get("department_id");
    setBusy(true);
    try {
      await api(`/clients/${clientId}/portal-users`, { method: "POST", body: JSON.stringify({ name: data.get("name"), email: data.get("email"), password: data.get("password"), department_id: department || null }) });
      form.reset();
      toast.success(t("clients.detail.portalUserAdded"));
      await load();
    } catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }
  async function setDepartment(u: PortalUser, department_id: string) {
    try { await api(`/clients/${clientId}/portal-users/${u.id}`, { method: "PATCH", body: JSON.stringify({ department_id: department_id || null }) }); await load(); }
    catch (err) { toast.error(messageFrom(err)); }
  }
  async function toggle(u: PortalUser) {
    try { await api(`/clients/${clientId}/portal-users/${u.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !u.is_active }) }); await load(); }
    catch (err) { toast.error(messageFrom(err)); }
  }
  async function removeUser(u: PortalUser) {
    try { await api(`/clients/${clientId}/portal-users/${u.id}`, { method: "DELETE" }); toast.success(t("clients.detail.portalUserRemoved")); await load(); }
    catch (err) { toast.error(messageFrom(err)); }
  }

  return <section className="form-section"><div className="section-copy"><h2>{t("clients.detail.portalUsersTitle")}</h2><p>{t("clients.detail.portalUsersCopy")}</p></div><div className="form-fields">
    {users === null ? <ListRowsSkeleton rows={2} /> : users.length ? <div className="table-shell"><table className="data-table"><tbody>
      {users.map((u) => <tr key={u.id}>
        <td><span className="entity-cell"><span className="agent-avatar"><UserRound size={17} /></span><span><strong>{u.name || u.email}</strong>{u.name && <small style={{ display: "block", color: "#89909d" }}>{u.email}</small>}</span></span></td>
        {departments.length > 0 && <td><select value={u.department_id ?? ""} onChange={(e) => setDepartment(u, e.target.value)} aria-label={t("clients.detail.portalUserDepartment")}><option value="">{t("clients.detail.portalUserAllDepartments")}</option>{departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></td>}
        <td><StatusBadge active={u.is_active} /></td>
        <td><button type="button" className="text-button" onClick={() => toggle(u)}>{u.is_active ? t("clients.detail.portalUserSuspend") : t("clients.detail.portalUserActivate")}</button></td>
        <td><button type="button" className="text-button danger-text" onClick={() => removeUser(u)} aria-label={t("clients.detail.portalUserRemove")}><Trash2 size={15} /></button></td>
      </tr>)}
    </tbody></table></div> : <p className="field-help">{t("clients.detail.portalUsersEmpty")}</p>}
    <form onSubmit={add} className="form-fields">
      <div className="form-grid">
        <label>{t("clients.detail.portalUserName")}<input name="name" required minLength={2} /></label>
        <label>{t("clients.detail.portalUserEmail")}<input name="email" required type="email" placeholder={t("clients.detail.portalEmailPlaceholder")} /></label>
      </div>
      <div className="form-grid">
        <label>{t("clients.detail.portalUserPassword")}<input name="password" required type="password" minLength={8} autoComplete="new-password" placeholder={t("clients.detail.portalPasswordMin")} /></label>
        {departments.length > 0 && <label>{t("clients.detail.portalUserDepartment")}<select name="department_id" defaultValue=""><option value="">{t("clients.detail.portalUserAllDepartments")}</option>{departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>}
      </div>
      <button className="button secondary align-start" disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <UserRound size={15} />} {t("clients.detail.portalUserAdd")}</button>
    </form>
  </div></section>;
}

function PortalDomain({ clientId }: { clientId: string }) {
  const t = useT();
  const toast = useToast();
  const [domain, setDomain] = useState<ClientDomain | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api<ClientDomain>(`/clients/${clientId}/domain`).then((d) => { setDomain(d); setInput(d.domain || ""); }); }, [clientId]);

  async function save() {
    setBusy(true);
    try { const d = await api<ClientDomain>(`/clients/${clientId}/domain`, { method: "PUT", body: JSON.stringify({ domain: input.trim().toLowerCase() }) }); setDomain(d); toast.success(t("clients.detail.domainSaved")); }
    catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }
  async function verify() {
    setBusy(true);
    try { const d = await api<ClientDomain>(`/clients/${clientId}/domain/verify`, { method: "POST" }); setDomain(d); toast.success(t("clients.detail.domainVerified")); }
    catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }
  async function remove() {
    setBusy(true);
    try { const d = await api<ClientDomain>(`/clients/${clientId}/domain`, { method: "DELETE" }); setDomain(d); setInput(""); toast.success(t("clients.detail.domainRemoved")); }
    catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }

  return <section className="form-section domain-section"><div className="section-copy"><h2>{t("clients.detail.domainTitle")}</h2><p>{t("clients.detail.domainCopy")}</p></div><div className="form-fields">
    <label>{t("clients.detail.domainLabel")}<div className="domain-input"><Globe2 size={16} /><input value={input} onChange={(e) => setInput(e.target.value)} placeholder="chat.brand.com" /><button type="button" className="button secondary" onClick={save} disabled={busy || !input.trim()}><Save size={15} /> {t("clients.detail.domainSave")}</button></div></label>
    {domain?.domain && <>
      <div className={`domain-status ${domain.verified ? "ok" : "pending"}`}>{domain.verified ? <><ShieldCheck size={16} /> {t("clients.detail.domainStatusVerified")}</> : <><ShieldAlert size={16} /> {t("clients.detail.domainStatusPending")}</>}</div>
      {!domain.verified && <div className="dns-instructions">
        <p>{t("clients.detail.domainDnsIntro")}</p>
        <table className="dns-table"><thead><tr><th>{t("clients.detail.domainDnsType")}</th><th>{t("clients.detail.domainDnsHost")}</th><th>{t("clients.detail.domainDnsValue")}</th></tr></thead><tbody>
          <tr><td>CNAME</td><td><code>{domain.domain}</code></td><td><code>{t("clients.detail.domainCnameTarget")}</code></td></tr>
          <tr><td>TXT</td><td><code>{domain.txt_host}</code></td><td><code>{domain.txt_value}</code></td></tr>
        </tbody></table>
        <div className="domain-actions"><button type="button" className="button primary" onClick={verify} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <ShieldCheck size={15} />} {t("clients.detail.domainVerify")}</button></div>
      </div>}
      <div className="form-footer"><button type="button" className="button danger" onClick={remove} disabled={busy}><Trash2 size={15} /> {t("clients.detail.domainRemove")}</button></div>
    </>}
  </div></section>;
}

function ClientInbox({ clientId }: { clientId: string }) {
  const t = useT();
  const toast = useToast();
  const [items, setItems] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [busy, setBusy] = useState(false);
  const load = async () => { const rows = await api<Conversation[]>(`/conversations?client_id=${clientId}`); setItems(rows); if (rows[0] && !selected) setSelected(await api<Conversation>(`/conversations/${rows[0].id}`)); };
  const [loadedInbox, setLoadedInbox] = useState(false);
  useEffect(() => { load().catch(() => {}).finally(() => setLoadedInbox(true)); }, [clientId]);
  async function choose(item: Conversation) { setSelected(await api<Conversation>(`/conversations/${item.id}`)); }
  async function mode(next: "ai" | "human") { if (!selected) return; setSelected(await api<Conversation>(`/conversations/${selected.id}/mode`, { method: "PATCH", body: JSON.stringify({ mode: next }) })); await load(); }
  async function reply(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (!selected) return; const form = event.currentTarget; const data = new FormData(form); setBusy(true); try { setSelected(await api<Conversation>(`/conversations/${selected.id}/reply`, { method: "POST", body: JSON.stringify({ content: data.get("content") }) })); form.reset(); await load(); } catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); } }
  if (!loadedInbox) return <ListRowsSkeleton rows={5} />;
  if (!items.length) return <EmptyState icon={<Inbox />} title={t("clients.detail.inboxEmptyTitle")} description={t("clients.detail.inboxEmptyDescription")} />;
  return <div className="inbox-layout"><aside className="inbox-list"><header><strong>{t("clients.detail.conversations")}</strong><span>{items.length}</span></header>{items.map((item) => <button key={item.id} className={selected?.id === item.id ? "active" : ""} onClick={() => choose(item)}><span className="entity-avatar tiny"><UserRound size={15} /></span><span><strong>{item.title}</strong><small>{item.channel} · {item.mode === "human" ? t("clients.detail.modeHuman") : t("clients.detail.modeAi")}</small></span></button>)}</aside><section className="inbox-thread">{selected && <><header><div><strong>{selected.title}</strong><small>{selected.channel}</small></div><button className={`mode-toggle ${selected.mode}`} onClick={() => mode(selected.mode === "ai" ? "human" : "ai")}>{selected.mode === "ai" ? t("clients.detail.takeControl") : t("clients.detail.returnToAi")}</button></header><div className="inbox-messages">{selected.messages?.map((message) => <div key={message.id} className={`inbox-message ${message.role}`}><small>{message.sender_name || (message.role === "assistant" ? t("clients.detail.senderAgent") : t("clients.detail.senderVisitor"))}</small><p>{message.content}</p></div>)}</div><form className="inbox-composer" onSubmit={reply}><input name="content" placeholder={selected.mode === "human" ? t("clients.detail.composerHuman") : t("clients.detail.composerLocked")} disabled={selected.mode !== "human" || busy} required /><button disabled={selected.mode !== "human" || busy}>{t("clients.detail.send")}</button></form></>}</section></div>;
}
