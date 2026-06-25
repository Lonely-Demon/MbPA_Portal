/*  Mumbai Port Authority — EODB Building Permission Portal
    Google Apps Script backend  (fetch / POST-JSON model — "paste the URL" style)
    ---------------------------------------------------------------------------
    The HTML page POSTs JSON to this Web App's /exec URL and reads JSON back.
    No google.script.run, so the HTML can be hosted anywhere and still send
    real OTP e-mail + write to Drive.

    ============  ONE-TIME SETUP  (do every step, in order)  ============
    1.  script.google.com  >  New project.  Paste THIS file into Code.gs.
    2.  Run > select  authorize  > Run.  Approve the Gmail + Drive scopes.
        You should get a "scopes authorised" test mail. If not, fix permissions
        before continuing — nothing else will work.
    3.  Run > select  seedOfficers  > Run.  This creates the 3 officer logins
        (hashed) and the Drive folders. Re-running is safe (it skips existing).
    4.  Run > select  installSlaTrigger  > Run.  This installs a DAILY trigger
        that runs runSlaSweep() — the 7-working-day auto-promotion + complaint
        logic. Without it, SLA promotion will not happen automatically.
    5.  Deploy > New deployment > type = Web app.
          Execute as:        Me
          Who has access:    Anyone
        Deploy > copy the  /exec  URL.
    6.  Open index.html, find  const ENDPOINT = "...",  paste that /exec URL.
    7.  (Optional) Upload a PDF named exactly  Document_Formats.pdf  into the
        Drive parent folder below. The "Document formats" button serves it.
    8.  After ANY later code change: Deploy > Manage deployments > (edit) >
        Version = New version > Deploy.  A redeploy without a new version
        keeps serving the OLD code.

    SECURITY NOTES
    - Passwords are never stored in plaintext. We keep a per-user random salt
      and SHA-256(salt + ':' + password). The Drive credentials mirror also
      stores only the hash. There is no way to recover a password from this.
    - The "45-minute applicant session" is enforced two ways: a client timer
      that resets the page, and a 45-min server token TTL. Officer tokens have
      a long TTL (no practical limit).
    - Consumer Gmail outbound quota is ~100 recipients/day. Watch the volume.
*/

/* ============================  CONFIG  ============================ */
const PARENT_FOLDER_ID = '1c52H9GMC-afyzzZMOfGjKZ8iXd-p4aXM';   // Drive folder that holds everything
const NOTIFY_TO        = 'dharshaemediagroups@gmail.com';        // internal intake mailbox
const SENDER_NAME      = 'Mumbai Port Authority — Building Permission Portal';
const STATUS_LINK      = 'https://dharshaemediagroup.dpdns.org'; // "verify your status" link in e-mails
const FORMATS_PDF_NAME = 'Document_Formats.pdf';                 // optional file in the parent folder

const OTP_TTL          = 600;     // OTP validity (10 min)
const APPLICANT_TTL    = 2700;    // applicant session token TTL (45 min)
const OFFICER_TTL      = 21600;   // officer session token TTL (6 h; refreshed on use)
const DEFAULT_SLA_DAYS = 7;       // fallback only \u2014 every step below sets its own slaDays

// Each UPDR-2026 milestone (S1\u2013S7, DEMO) is cleared by one or more officers acting in
// sequence ("chain"). Per direct instruction (2026-06-19): Estate NOC + Junior Planner's
// Approval in Principle share ONE combined 21-working-day clock for S1 \u2014 both steps' slaDays
// are 21 and advanceAfterApproval_ does NOT reset rec.stageStartedAt when moving Estate->JP
// within S1, so JP continues counting down the SAME clock Estate was on instead of getting its
// own fresh window. (Supersedes an earlier 21 + 30 = 51-day combined total.)
// anchorKey, when present, means this step's SLA clock starts from the approval timestamp of
// the named step (a key in rec.stepLog) rather than from when this step itself became current
// \u2014 used for S2-DP, whose 30-day clock is anchored to the Right-to-Development approval.
const MILESTONE_CHAIN = {
  S1:   [ { role:'Estate Officer', key:'S1-RDO', slaDays:21, label:'Right to Development (Estate NOC)' },
          { role:'Junior Planner', key:'S1-JP',  slaDays:21, label:'Approval in Principle' } ],
  S2:   [ { role:'Deputy Planner', key:'S2-DP',  slaDays:30, label:'Development Permission + CC to Plinth', anchorKey:'S1-RDO' } ],
  S3:   [ { role:'Deputy Planner', key:'S3-DP',  slaDays:7,  label:'Plinth Completion / Further CC' } ],
  S4:   [ { role:'Junior Planner', key:'S4-JP',  slaDays:7,  label:'Commencement Certificate \u2014 80% BUA' } ],
  S5:   [ { role:'Deputy Planner', key:'S5-DP',  slaDays:15, label:'Commencement Certificate \u2014 Remaining 20% BUA' } ],
  S6:   [ { role:'Deputy Planner', key:'S6-DP',  slaDays:7,  label:'Drainage & Building Completion' } ],
  S7:   [ { role:'Chairman',       key:'S7-CH',  slaDays:15, label:'Occupancy Certificate', final:true } ],
  // Re-erection's pre-step (demolition + site clearance). NOT covered by Table B.1 Part B or by
  // any explicit instruction \u2014 Estate Officer / 10-day SLA here is an ASSUMPTION pending
  // confirmation, not a sourced UPDR-2026 value.
  DEMO: [ { role:'Estate Officer', key:'DEMO-EO', slaDays:10, label:'Demolition & Site Clearance' } ]
};

// Officer credentials to seed (run seedOfficers once). Plaintext lives ONLY here,
// in source, for seeding; it is hashed on write and never stored in plaintext.
// "stage" is now a legacy display number only \u2014 officer routing matches on ROLE
// (see currentStep_ / OFFICER_BY_ROLE below), so the same role may legitimately appear
// in more than one milestone's chain (Estate Officer: S1 + DEMO; Junior Planner: S1 + S4).
const OFFICER_SEED = [
  { role: 'Estate Officer',  email: 'quasarsxx@gmail.com',              name: 'Quasar',       username: 'Quasar',       password: 'Quasar',     stage: 1 },
  { role: 'Junior Planner',  email: 'anvi1001bp24@spa.ac.in',           name: 'Anvi',         username: 'Anvi',         password: '20042006',   stage: 1 },
  { role: 'Deputy Planner',  email: 'dlprahadees07@gmail.com',          name: 'Prahadeesvar', username: 'Prahadeesvar', password: '29072006',   stage: 2 },
  { role: 'Chairman',        email: 'dharshanmanivelpandian@gmail.com', name: 'Dharshan',     username: 'Dharshan',     password: '17022007',   stage: 7 }
];
const OFFICER_BY_ROLE = {};
OFFICER_SEED.forEach(function (o) { OFFICER_BY_ROLE[o.role] = o; });

// Resolves the officer currently responsible for `rec`, plus the milestone-chain step
// metadata (SLA days, label, anchor, final-ness). This is the single source of truth that
// replaces the old fixed 3-officer STAGES[] array; every routing/SLA/email site below reads
// through this instead of indexing a numeric stage.
function currentStep_(rec) {
  const streamCfg = streamById_(rec.stream);
  const milestoneIdx = Math.min(Math.max(rec.milestoneIdx || 1, 1), streamCfg.stages.length);
  const milestone = streamCfg.stages[milestoneIdx - 1];
  const chain = MILESTONE_CHAIN[milestone.id] || [{ role: 'Junior Planner', key: milestone.id + '-1', slaDays: DEFAULT_SLA_DAYS, label: milestone.name }];
  const approverStep = Math.min(Math.max(rec.approverStep || 1, 1), chain.length);
  const step = chain[approverStep - 1];
  const officer = OFFICER_BY_ROLE[step.role] || { email: '', name: step.role };
  return {
    role: step.role, email: officer.email, name: officer.name,
    slaDays: step.slaDays || DEFAULT_SLA_DAYS, key: step.key, anchorKey: step.anchorKey || '',
    label: step.label, final: !!step.final,
    approverStep: approverStep, chainLen: chain.length, isLastStepOfMilestone: approverStep >= chain.length,
    milestone: milestone, milestoneIdx: milestoneIdx, streamCfg: streamCfg
  };
}
// Working-day SLA remaining for the CURRENT step, honouring anchorKey if the step has one.
function slaRemaining_(rec, cur, now) {
  const startedAt = (cur.anchorKey && rec.stepLog && rec.stepLog[cur.anchorKey])
    ? new Date(rec.stepLog[cur.anchorKey]) : new Date(rec.stageStartedAt || rec.filedAt);
  const elapsed = workingDaysBetween_(startedAt, now || new Date());
  return Math.max(0, cur.slaDays - elapsed);
}
// Shared "this step just cleared" transition \u2014 used by both an officer's explicit approval
// (officerDecision_) and the SLA auto-promotion sweep (runSlaSweep). Mutates `rec` in place;
// the caller still does registerApplication_ and any officer-only side effects (e.g. the
// certificate-PDF prompt, which only makes sense from the live officer UI).
function advanceAfterApproval_(rec, cur, nowIso) {
  rec.stepLog = rec.stepLog || {};
  rec.stepLog[cur.key] = nowIso;

  if (!cur.isLastStepOfMilestone) {
    rec.approverStep = cur.approverStep + 1;
    // NOTE: stageStartedAt is intentionally NOT reset here. Chained steps within the same
    // milestone (e.g. S1 Estate Officer -> Junior Planner) share one combined SLA clock running
    // from when the milestone itself started, not a fresh window per step. A step with its own
    // anchorKey (e.g. cross-milestone S2-DP) overrides this via stepLog regardless.
    return { kind: 'stepAdvanced', next: currentStep_(rec) };
  }

  rec.milestoneHistory = rec.milestoneHistory || [];
  rec.milestoneHistory.push({ at: nowIso, milestone: cur.milestone.id, idx: cur.milestoneIdx, name: cur.milestone.name, output: cur.milestone.milestone });

  if (cur.final || cur.milestoneIdx >= cur.streamCfg.stages.length) {
    rec.state = 'approved_final';
    return { kind: 'finalApproved' };
  }

  rec.milestoneIdx = cur.milestoneIdx + 1;
  rec.approverStep = 1;
  rec.stageStartedAt = nowIso;
  rec.state = 'awaiting_next_milestone';
  return { kind: 'milestoneAdvanced', nextMilestone: cur.streamCfg.stages[rec.milestoneIdx - 1] };
}
// Appends the application's reference to a client-sent filename so Drive listings are unique
// across applicants regardless of what the applicant/officer named the file locally, e.g.
// "Concession_justification.jpg" -> "Concession_justification_MBPASPA2026061.jpg".
function withRefSuffix_(name, reference) {
  const n = String(name || 'document');
  const dot = n.lastIndexOf('.');
  const base = dot > 0 ? n.slice(0, dot) : n;
  const ext = dot > 0 ? n.slice(dot) : '';
  return base + '_' + reference + ext;
}
// Wraps MailApp.sendEmail so a failure (most commonly: the sender account's daily Gmail quota
// is exhausted, or a recipient address is invalid) is LOGGED instead of disappearing silently.
// Check Apps Script editor -> Executions for these entries; check
// MailApp.getRemainingDailyQuota() if they correlate with heavy testing volume.
function safeMail_(opts) {
  try { MailApp.sendEmail(opts); return true; }
  catch (err) {
    Logger.log('safeMail_ FAILED -> to=' + opts.to + ' | subject=' + opts.subject + ' | error=' + String(err && err.message || err));
    return false;
  }
}

/* ====================  RUN ONCE FROM THE EDITOR  ==================== */
function authorize() {
  const me = Session.getActiveUser().getEmail();
  MailApp.sendEmail({
    to: me, name: SENDER_NAME,
    subject: 'MbPA portal — scopes authorised',
    htmlBody: '<p>Gmail + Drive access is granted and outbound mail works.</p>' +
              '<p>Remaining mail quota today: <b>' + MailApp.getRemainingDailyQuota() + '</b></p>'
  });
  ensureFolders_();
  Logger.log('Authorized OK. Test mail sent to ' + me + '. Remaining quota: ' + MailApp.getRemainingDailyQuota());
}

function seedOfficers() {
  ensureFolders_();
  let made = 0, skipped = 0;
  OFFICER_SEED.forEach(function (o) {
    const existing = getUserByEmail_(o.email);
    if (existing && existing.role !== 'applicant') { skipped++; return; }
    const salt = Utilities.getUuid();
    const rec = {
      role: o.role, stage: o.stage, name: o.name, surname: '',
      email: String(o.email).toLowerCase(), username: o.username,
      aadhaar: '', age: '', sex: '', phone: '',
      salt: salt, hash: hashPw_(o.password, salt),
      createdAt: new Date().toISOString()
    };
    writeUser_(rec);
    made++;
  });
  Logger.log('seedOfficers done. created=' + made + ' skipped=' + skipped + '. No credentials email is sent — share logins with officers directly.');
}

function installSlaTrigger() {
  // remove any existing runSlaSweep triggers, then install one daily
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runSlaSweep') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('runSlaSweep').timeBased().everyDays(1).atHour(2).create();
  Logger.log('Daily SLA trigger installed (runs ~02:00).');
}

/* ============================  ROUTER  ============================ */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}
function doGet(e) {
  try {
    return HtmlService.createTemplateFromFile('Index')
      .evaluate()
      .setTitle('Mumbai Port Authority — Building Permission Portal')
      .addMetaTag('viewport', 'width=device-width, initial-scale=1')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  } catch (err) {
    return json_({ ok: true, service: 'MbPA EODB Portal', hint: 'POST JSON {"action":"ping"} to this URL.' });
  }
}

function doPost(e) { return json_(handle_(e)); }

function handle_(e) {
  try {
    let body = {};
    if (e && e.postData && e.postData.contents) body = JSON.parse(e.postData.contents);
    else if (e && e.parameter && e.parameter.payload) body = JSON.parse(e.parameter.payload);

    switch (String(body.action || '')) {
      case 'ping':              return { ok: true, pong: true };

      /* UPDR-2026 stream / lifecycle / fee config (Pass 1, additive) */
      case 'getStreamConfig':   return getStreamConfig_(body);
      case 'calcFees':          return calcFees_(body);

      /* auth */
      case 'signupSendOtp':     return signupSendOtp_(body);
      case 'signupCreate':      return signupCreate_(body);
      case 'loginRequest':      return loginRequest_(body);
      case 'loginVerify':       return loginVerify_(body);
      case 'session':           return sessionInfo_(body);

      /* generic OTP (still used by Know-your-status) */
      case 'sendOtp':           return sendOtp_(body);
      case 'verifyOtp':         return verifyOtp_(body);

      /* applicant */
      case 'reserveReference':  return reserveReference_(body);
      case 'submit':
      case 'submitApplication': return submitApplication_(body);
      case 'submitCorrection':  return submitCorrection_(body);
      case 'submitMilestone':   return submitMilestone_(body);
      case 'myApplicationStatus': return myApplicationStatus_(body);
      case 'statusLookup':      return statusLookup_(body);
      case 'getStatus':         return getStatus_(body);
      case 'getMyApplications': return getMyApplications_(body);
      case 'formatsInfo':       return formatsInfo_(body);
      case 'raiseComplaint':    return raiseComplaint_(body);

      /* officer */
      case 'officerInbox':      return officerInbox_(body);
      case 'officerOpen':       return officerOpen_(body);
      case 'officerDecision':   return officerDecision_(body);
      case 'uploadCertificate': return uploadCertificate_(body);
      case 'getFinalDossier':   return getFinalDossier_(body);
      case 'submitFinalDossier': return submitFinalDossier_(body);

      default:                  return { ok: false, error: 'unknown action: ' + body.action };
    }
  } catch (err) {
    return { ok: false, error: String(err && err.message || err) };
  }
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

/* ============================  HASHING  ============================ */
function hashPw_(pw, salt) {
  const raw = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, String(salt) + ':' + String(pw), Utilities.Charset.UTF_8);
  return Utilities.base64Encode(raw);
}
function checkPw_(pw, rec) { return rec && rec.hash && rec.hash === hashPw_(pw, rec.salt); }

/* ============================  USER STORE  ============================ */
/* Keyed in Script Properties; mirrored as JSON (hash only) into Drive _credentials. */
function userKey_(email)     { return 'user_'   + String(email).toLowerCase(); }
function aadhaarKey_(a)      { return 'aadh_'   + digits_(a); }
function unameKey_(u)        { return 'uname_'  + String(u).toLowerCase(); }

function getUserByEmail_(email) {
  const r = PropertiesService.getScriptProperties().getProperty(userKey_(email));
  return r ? JSON.parse(r) : null;
}
function emailForAadhaar_(a) { return PropertiesService.getScriptProperties().getProperty(aadhaarKey_(a)) || ''; }
function emailForUsername_(u){ return PropertiesService.getScriptProperties().getProperty(unameKey_(u)) || ''; }

function writeUser_(rec) {
  const props = PropertiesService.getScriptProperties();
  props.setProperty(userKey_(rec.email), JSON.stringify(rec));
  if (rec.aadhaar)  props.setProperty(aadhaarKey_(rec.aadhaar), rec.email);
  if (rec.username) props.setProperty(unameKey_(rec.username), rec.email);
  // Drive mirror (hash only — never plaintext)
  try {
    const folder = getCredentialsFolder_();
    const fname = sanitizeFile_((rec.role === 'applicant' ? 'applicant' : 'officer') + '_' + rec.email) + '.json';
    const safe = JSON.parse(JSON.stringify(rec));
    const it = folder.getFilesByName(fname);
    const content = JSON.stringify(safe, null, 2);
    if (it.hasNext()) it.next().setContent(content); else folder.createFile(fname, content, 'application/json');
  } catch (err) { /* mirror is best-effort */ }
}

/* ============================  SIGN-UP  ============================ */
function signupSendOtp_(body) {
  const email = String(body.email || '').trim().toLowerCase();
  const aadhaar = digits_(body.aadhaar);
  const username = String(body.username || '').trim();

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return { ok: false, error: 'Enter a valid email address.' };
  if (aadhaar.length !== 12) return { ok: false, error: 'Aadhaar must be 12 digits.' };
  if (username.length < 3)   return { ok: false, error: 'Choose a username of at least 3 characters.' };

  // email already an account?
  if (getUserByEmail_(email)) return { ok: false, error: 'An account already exists for this email. Please sign in.' };
  // username taken?
  if (emailForUsername_(username)) return { ok: false, error: 'That username is already taken — choose another.' };
  // aadhaar already used? -> block AND warn the registered owner
  const owner = emailForAadhaar_(aadhaar);
  if (owner) {
    try {
      MailApp.sendEmail({
        to: owner, name: SENDER_NAME,
        subject: 'Security alert — your Aadhaar was used in a new registration attempt',
        htmlBody: securityAlertHtml_()
      });
    } catch (e) {}
    return { ok: false, error: 'An account already exists against this Aadhaar number. The registered email has been notified.' };
  }

  const code  = sixDigit_();
  const otpId = Utilities.getUuid();
  CacheService.getScriptCache().put('otp_' + otpId,
    JSON.stringify({ code: code, email: email, purpose: 'signup', verified: false }), OTP_TTL);
  MailApp.sendEmail({ to: email, name: SENDER_NAME,
    subject: 'Verify your email — MbPA Building Permission Portal', htmlBody: otpEmailHtml_(code) });
  return { ok: true, otpId: otpId };
}

function signupCreate_(body) {
  const cache = CacheService.getScriptCache();
  const raw = cache.get('otp_' + String(body.otpId));
  if (!raw) return { ok: false, error: 'Verification expired — request a new code.' };
  const otp = JSON.parse(raw);
  if (String(body.code) !== String(otp.code)) return { ok: false, error: 'Incorrect code.' };

  const p = body.profile || {};
  const email = String(p.email || otp.email || '').trim().toLowerCase();
  const aadhaar = digits_(p.aadhaar);
  const username = String(p.username || '').trim();
  const name = String(p.name || '').trim();
  const password = String(p.password || '');

  if (!name) return { ok: false, error: 'Name is required.' };
  if (aadhaar.length !== 12) return { ok: false, error: 'Aadhaar must be 12 digits.' };
  if (!username) return { ok: false, error: 'Username is required.' };
  if (password.length < 6) return { ok: false, error: 'Password must be at least 6 characters.' };
  if (email !== String(otp.email).toLowerCase()) return { ok: false, error: 'Email mismatch — restart sign-up.' };

  // re-check uniqueness at the moment of creation (race-safety)
  if (getUserByEmail_(email)) return { ok: false, error: 'An account already exists for this email.' };
  if (emailForUsername_(username)) return { ok: false, error: 'That username is already taken.' };
  if (emailForAadhaar_(aadhaar)) return { ok: false, error: 'An account already exists against this Aadhaar number.' };

  const salt = Utilities.getUuid();
  const rec = {
    role: 'applicant',
    name: name, surname: String(p.surname || '').trim(),
    aadhaar: aadhaar, age: String(p.age || '').trim(), sex: String(p.sex || '').trim(),
    phone: String(p.phone || '').trim(), email: email, username: username,
    salt: salt, hash: hashPw_(password, salt), createdAt: new Date().toISOString()
  };
  writeUser_(rec);
  cache.remove('otp_' + String(body.otpId));
  return { ok: true, email: email };
}

/* ============================  LOGIN  ============================ */
function loginRequest_(body) {
  const email = String(body.email || '').trim().toLowerCase();
  const username = String(body.username || '').trim();
  const password = String(body.password || '');
  const generic = { ok: false, error: 'Email, username and password do not match an account.' };

  if (!email || !username || !password) return generic;
  const rec = getUserByEmail_(email);
  if (!rec) return generic;
  if (String(rec.username).toLowerCase() !== username.toLowerCase()) return generic;
  if (!checkPw_(password, rec)) return generic;

  const code  = sixDigit_();
  const otpId = Utilities.getUuid();
  CacheService.getScriptCache().put('otp_' + otpId,
    JSON.stringify({ code: code, email: email, purpose: 'login', role: rec.role, verified: false }), OTP_TTL);
  MailApp.sendEmail({ to: rec.email, name: SENDER_NAME,
    subject: 'Your sign-in code — MbPA Building Permission Portal', htmlBody: otpEmailHtml_(code) });
  return { ok: true, otpId: otpId, emailMasked: maskEmail_(rec.email), role: rec.role };
}

function loginVerify_(body) {
  const cache = CacheService.getScriptCache();
  const raw = cache.get('otp_' + String(body.otpId));
  if (!raw) return { ok: false, error: 'Code expired — request a new one.' };
  const otp = JSON.parse(raw);
  if (String(body.code) !== String(otp.code)) return { ok: false, error: 'Incorrect code.' };

  const rec = getUserByEmail_(otp.email);
  if (!rec) return { ok: false, error: 'Account not found.' };

  // Mint a session token. Reuse the 'otp_'+token namespace with verified:true so
  // submitApplication_ (which checks otp verified) accepts it directly.
  const token = Utilities.getUuid();
  const ttl = (rec.role === 'applicant') ? APPLICANT_TTL : OFFICER_TTL;
  cache.put('otp_' + token, JSON.stringify({ verified: true, email: rec.email, role: rec.role, stage: rec.stage || 0 }), ttl);
  cache.remove('otp_' + String(body.otpId));

  return {
    ok: true, token: token, role: rec.role, stage: rec.stage || 0,
    ttl: ttl,
    profile: {
      name: rec.name || '', surname: rec.surname || '', email: rec.email,
      phone: rec.phone || '', aadhaar: rec.aadhaar || '', age: rec.age || '', sex: rec.sex || '',
      role: rec.role, roleLabel: rec.role === 'applicant' ? 'Applicant' : rec.role
    }
  };
}

function sessionInfo_(body) {
  const s = readToken_(body.token);
  if (!s) return { ok: false, error: 'expired' };
  return { ok: true, email: s.email, role: s.role, stage: s.stage || 0 };
}
function readToken_(token) {
  const raw = CacheService.getScriptCache().get('otp_' + String(token || ''));
  if (!raw) return null;
  const s = JSON.parse(raw);
  if (!s.verified) return null;
  // refresh officer sessions on use
  if (s.role && s.role !== 'applicant') CacheService.getScriptCache().put('otp_' + String(token), raw, OFFICER_TTL);
  return s;
}

/* ===================  REFERENCE NUMBERS  =================== */
function nextReference_() {
  const tz = Session.getScriptTimeZone() || 'Asia/Kolkata';
  const now = new Date();
  const yyyy = Utilities.formatDate(now, tz, 'yyyy');
  const mm   = Utilities.formatDate(now, tz, 'MM');
  const key  = 'seq_' + yyyy + mm;
  const lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    const props = PropertiesService.getScriptProperties();
    const n = (parseInt(props.getProperty(key), 10) || 0) + 1;
    props.setProperty(key, String(n));
    return 'MBPASPA' + yyyy + mm + n;
  } finally { lock.releaseLock(); }
}
function reserveReference_(body) { return { ok: true, reference: nextReference_() }; }

/* ===========================  SUBMISSION  =========================== */
function submitApplication_(data) {
  const sess = readToken_(data.otpId);
  if (!sess) return { ok: false, error: 'Your session has expired — please sign in again.' };
  const email = String(data.email || sess.email || '').trim();
  if (!email) return { ok: false, error: 'No applicant email.' };

  let reference = sanitizeFile_(String(data.reference || '').toUpperCase().replace(/\s+/g, ''));
  if (!/^MBPASPA\d{6}\d+$/.test(reference)) reference = nextReference_();
  data.reference = reference;

  // Per-application folder with the two required sub-folders.
  const folder   = getRefFolder_(reference);
  const appFolder = getOrCreateChild_(folder, 'Application Document');  // merged form + all docs
  const upFolder  = getOrCreateChild_(folder, 'Uploaded Documents');    // raw uploads only (no app form)

  let pdfUrl = '';
  if (data.pdfBase64) {
    const pdfName = sanitizeFile_(data.pdfName || ('Application_' + reference + '.pdf'));
    const pdfBlob = Utilities.newBlob(Utilities.base64Decode(data.pdfBase64), 'application/pdf', pdfName);
    pdfUrl = appFolder.createFile(pdfBlob).getUrl();

    // raw uploaded documents go ONLY into "Uploaded Documents" (not the merged form)
    (data.files || []).forEach(function (f) {
      if (!f || !f.base64) return;
      upFolder.createFile(Utilities.newBlob(Utilities.base64Decode(f.base64),
        f.mimeType || 'application/octet-stream', sanitizeFile_(withRefSuffix_(f.name || 'document', reference))));
    });

    // acknowledge to applicant with the merged PDF attached
    safeMail_({ to: email, name: SENDER_NAME,
      subject: 'Application received — ' + reference + ' · MbPA',
      htmlBody: ackEmailHtml_(data),
      attachments: [pdfBlob.copyBlob().setName(pdfName)] });
  }

  // plain-text record
  appFolder.createFile(reference + '.txt', refTxt_(reference, data, email), 'text/plain');

  // register with workflow state — starts at Milestone 1 of the applicant's chosen
  // UPDR-2026 stream (S1 for every stream except Re-erection, which starts at DEMO);
  // currentStep_ resolves the first officer in that milestone's chain dynamically.
  const nowIso = new Date().toISOString();
  const rec = {
    email: email,
    applicantName: data.applicantName || '',
    phone: data.phone || '',
    summary: data.summary || '',
    dateStr: data.dateStr || today_(),
    filedAt: data.submittedAt || nowIso,
    approverStep: 1,
    stepLog: {},
    state: 'under_scrutiny',           // under_scrutiny | awaiting_next_milestone | rejected | approved_final
    stageStartedAt: nowIso,
    history: [{ at: nowIso, event: 'filed', by: 'Applicant' }],
    rejectedDocs: [],
    rejectedReasons: {},
    rejectedByRole: '',
    correctionDeadline: '',
    complaintAgainst: [],              // list of officer roles flagged for SLA breach
    folderUrl: folder.getUrl(),
    appFolderUrl: appFolder.getUrl(),
    uploadFolderUrl: upFolder.getUrl(),
    pdfUrl: pdfUrl,
    // --- UPDR-2026 lifecycle (Pass 2, additive) ---
    stream: streamById_(data.stream).id,
    milestoneIdx: 1,
    milestoneHistory: [],
    bua: Number(data.bua || data.estimatedBUA || 0) || 0,
    concessions: Array.isArray(data.concessions) ? data.concessions.slice(0, 20) : [],
    zonalRrr: Number(data.zonalRrr || 0) || 0,
    payments: [],
    certificates: []
  };
  registerApplication_(reference, rec);

  // notify the first officer of the first milestone + internal intake
  notifyOfficerNew_(currentStep_(rec), reference, data);
  safeMail_({ to: NOTIFY_TO, name: SENDER_NAME,
    subject: 'New building-permission application — ' + reference,
    htmlBody: intakeEmailHtml_(data, folder.getUrl()) });

  return { ok: true, reference: reference, folderUrl: folder.getUrl(), pdfUrl: pdfUrl };
}

/* =====================  CORRECTION RE-SUBMISSION  ===================== */
function submitCorrection_(data) {
  const sess = readToken_(data.otpId);
  if (!sess) return { ok: false, error: 'Your session has expired — please sign in again.' };

  const reference = sanitizeFile_(String(data.reference || '').toUpperCase().replace(/\s+/g, ''));
  const rec = getApplication_(reference);
  if (!rec) return { ok: false, error: 'not_found' };
  if (String(sess.email).toLowerCase() !== String(rec.email).toLowerCase())
    return { ok: false, error: 'This application is not registered to your account.' };
  if (rec.state !== 'rejected') return { ok: false, error: 'This application is not awaiting correction.' };

  // store corrected uploads in a fresh dated "Corrected" subfolder. Milestone-1 keeps the
  // exact original path (Application Document/Corrected Documents <stamp>/); milestone 2+
  // routes into that milestone's own folder instead.
  const folder = getRefFolder_(reference);
  const stamp  = Utilities.formatDate(new Date(), Session.getScriptTimeZone() || 'Asia/Kolkata', 'yyyyMMdd_HHmm');
  const milestoneIdx = rec.milestoneIdx || 1;
  let corrFolder;
  if (milestoneIdx > 1) {
    const streamCfg = streamById_(rec.stream);
    const ms = streamCfg.stages[milestoneIdx - 1];
    const msFolder = getOrCreateChild_(folder, ms ? ('Milestone ' + ms.id + ' \u2014 ' + ms.name) : ('Milestone ' + milestoneIdx));
    corrFolder = msFolder.createFolder('Corrected ' + stamp);
  } else {
    const appFolder = getOrCreateChild_(folder, 'Application Document');
    corrFolder = appFolder.createFolder('Corrected Documents ' + stamp);
  }
  (data.files || []).forEach(function (f) {
    if (!f || !f.base64) return;
    corrFolder.createFile(Utilities.newBlob(Utilities.base64Decode(f.base64),
      f.mimeType || 'application/octet-stream', sanitizeFile_(withRefSuffix_(f.name || 'document', reference))));
  });

  // back under scrutiny at the SAME step that rejected it (approverStep/milestoneIdx are
  // untouched by a rejection, so currentStep_ already resolves back to that same officer);
  // reset the clock.
  const nowIso = new Date().toISOString();
  rec.state = 'under_scrutiny';
  rec.stageStartedAt = nowIso;
  rec.rejectedDocs = [];
  rec.rejectedReasons = {};
  rec.rejectedByRole = '';
  rec.correctionDeadline = '';
  rec.history.push({ at: nowIso, event: 'corrected_resubmitted', by: 'Applicant', folder: corrFolder.getUrl() });
  registerApplication_(reference, rec);

  // notify the officer at that step
  const cur = currentStep_(rec);
  safeMail_({ to: cur.email, name: SENDER_NAME,
    subject: 'Corrected documents received — ' + reference,
    htmlBody: officerCorrectedHtml_(reference, rec, corrFolder.getUrl()) });

  return { ok: true, reference: reference, folderUrl: corrFolder.getUrl() };
}

/* ===================  NEXT-MILESTONE FILING  =================== */
// Applicant files the CURRENT milestone's required documents (and, if that milestone has a
// payment touchpoint, a challan/transaction reference + optional receipt). Accepts either a
// logged-in session token or an OTP-verified "Know your status" id — same readToken_ pattern
// already used by submitCorrection_/raiseComplaint_.
function submitMilestone_(data) {
  const reference = sanitizeFile_(String(data.reference || '').toUpperCase().replace(/\s+/g, ''));
  const rec = getApplication_(reference);
  if (!rec) return { ok: false, error: 'not_found' };

  const sess = readToken_(data.otpId || data.token);
  if (!sess || String(sess.email).toLowerCase() !== String(rec.email).toLowerCase())
    return { ok: false, error: 'Verification expired — please sign in or verify your status again.' };
  if (rec.state !== 'awaiting_next_milestone') return { ok: false, error: 'This application is not awaiting the next stage.' };

  const streamCfg = streamById_(rec.stream);
  const milestoneIdx = rec.milestoneIdx || 1;
  const milestone = streamCfg.stages[milestoneIdx - 1];
  if (!milestone) return { ok: false, error: 'Stream/stage configuration error.' };

  if (milestone.pay !== 'none') {
    const challanRef = String(data.challanRef || '').trim();
    if (!challanRef) return { ok: false, error: 'Enter the challan / payment reference number.' };
    rec.payments = rec.payments || [];
    rec.payments.push({ milestone: milestone.id, idx: milestoneIdx, challanRef: challanRef.slice(0, 80),
      amount: Number(data.amount || 0) || null, at: new Date().toISOString() });
  }

  const folder = getRefFolder_(reference);
  const msFolder = getOrCreateChild_(folder, 'Milestone ' + milestone.id + ' \u2014 ' + milestone.name);
  (data.files || []).forEach(function (f) {
    if (!f || !f.base64) return;
    msFolder.createFile(Utilities.newBlob(Utilities.base64Decode(f.base64),
      f.mimeType || 'application/octet-stream', sanitizeFile_(withRefSuffix_(f.name || 'document', reference))));
  });
  if (data.receipt && data.receipt.base64) {
    const payFolder = getOrCreateChild_(msFolder, 'Payment Receipt');
    payFolder.createFile(Utilities.newBlob(Utilities.base64Decode(data.receipt.base64),
      data.receipt.mimeType || 'application/octet-stream', sanitizeFile_(withRefSuffix_(data.receipt.name || 'receipt', reference))));
  }

  const nowIso = new Date().toISOString();
  rec.state = 'under_scrutiny';
  rec.approverStep = 1;
  rec.stageStartedAt = nowIso;
  rec.history.push({ at: nowIso, event: 'milestone_filed', milestone: milestone.id, milestoneIdx: milestoneIdx, by: 'Applicant', folder: msFolder.getUrl() });
  registerApplication_(reference, rec);

  notifyOfficerNew_(currentStep_(rec), reference, rec);
  return { ok: true, reference: reference, milestone: milestone.name, folderUrl: msFolder.getUrl() };
}

/* ====================  KNOW YOUR STATUS  ==================== */
/* ====================  GENERIC OTP  (used by Know-your-status)  ==================== */
function sendOtp_(body) {
  const email = String(body.email || '').trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return { ok: false, error: 'Enter a valid email address.' };
  const code  = sixDigit_();
  const otpId = Utilities.getUuid();
  CacheService.getScriptCache().put('otp_' + otpId,
    JSON.stringify({ code: code, email: email, phone: String(body.phone || ''), verified: false }), OTP_TTL);
  MailApp.sendEmail({ to: email, name: SENDER_NAME,
    subject: 'Your verification code — MbPA Building Permission Portal', htmlBody: otpEmailHtml_(code) });
  return { ok: true, otpId: otpId, emailMasked: maskEmail_(email) };
}

function verifyOtp_(body) {
  const cache = CacheService.getScriptCache();
  const key = 'otp_' + String(body.otpId);
  const raw = cache.get(key);
  if (!raw) return { ok: false, error: 'expired' };
  let v; try { v = JSON.parse(raw); } catch (e) { return { ok: false, error: 'expired' }; }
  if (String(body.code) !== String(v.code)) return { ok: false, error: 'invalid' };
  // mark verified IN PLACE (same key) — getStatus_ re-reads this exact cache entry next
  v.verified = true;
  cache.put(key, JSON.stringify(v), OTP_TTL);
  return { ok: true };
}

function statusLookup_(body) {
  const reference = sanitizeFile_(String(body.reference || '').toUpperCase().replace(/\s+/g, ''));
  const rec = getApplication_(reference);
  if (!rec || !rec.email) return { ok: false, error: 'not_found' };

  const code  = sixDigit_();
  const otpId = Utilities.getUuid();
  CacheService.getScriptCache().put('otp_' + otpId,
    JSON.stringify({ code: code, email: rec.email, reference: reference, verified: false }), OTP_TTL);
  MailApp.sendEmail({ to: rec.email, name: SENDER_NAME,
    subject: 'Status-check code — ' + reference + ' · MbPA', htmlBody: otpEmailHtml_(code) });
  return { ok: true, otpId: otpId, emailMasked: maskEmail_(rec.email) };
}

function getStatus_(body) {
  const reference = sanitizeFile_(String(body.reference || '').toUpperCase().replace(/\s+/g, ''));
  const raw = CacheService.getScriptCache().get('otp_' + String(body.otpId));
  if (!raw) return { ok: false, error: 'Verification expired — request a new code.' };
  const v = JSON.parse(raw);
  if (!v.verified) return { ok: false, error: 'Not verified.' };

  const rec = getApplication_(reference);
  if (!rec) return { ok: false, error: 'not_found' };
  if (String(v.email).toLowerCase() !== String(rec.email).toLowerCase())
    return { ok: false, error: 'Verification does not match this application.' };

  return { ok: true, status: buildStatusView_(reference, rec) };
}

function buildStatusView_(reference, rec) {
  const cur = currentStep_(rec);
  const remaining = slaRemaining_(rec, cur);

  const streamCfg = cur.streamCfg;
  const milestoneIdx = cur.milestoneIdx;
  const curMilestone = cur.milestone;
  const isAwaitingNext = rec.state === 'awaiting_next_milestone';
  const chain = MILESTONE_CHAIN[curMilestone.id] || [];

  let stageLabel;
  if (rec.state === 'approved_final') stageLabel = 'Approved by Chairman \u2014 ' + curMilestone.milestone;
  else if (rec.state === 'rejected')  stageLabel = 'Returned for correction by ' + (rec.rejectedByRole || cur.role);
  else if (isAwaitingNext) stageLabel = 'Stage cleared \u2014 file ' + curMilestone.name + ' to continue';
  else stageLabel = 'Under scrutiny \u2014 ' + cur.role + ' \u00b7 ' + curMilestone.name +
    (cur.chainLen > 1 ? ' (step ' + cur.approverStep + ' of ' + cur.chainLen + ': ' + cur.label + ')' : '');

  // Fee/payment snapshot: only the Master Challan stage has a formula in UPDR-2026 (\u00a73).
  // Infra-utility and tax-arrears stages have no source formula, so we say so rather than
  // inventing a figure.
  let feeSnapshot = null, paymentNote = '';
  if (isAwaitingNext && curMilestone.pay !== 'none') {
    if (curMilestone.pay === 'master_challan') {
      const calc = calcFees_({ bua: rec.bua || 0, rrr: rec.zonalRrr || 0, concessions: rec.concessions || [] });
      feeSnapshot = calc.ok ? calc.fees : null;
    } else if (curMilestone.pay === 'infra_utility') {
      paymentNote = 'Pro-rata infrastructure / utility connection charges (roads, streetlights, drainage, water mains) apply at this stage. The amount is assessed by the Estate / Engineering division and is not auto-calculated by this portal \u2014 enter the challan reference once assessed and paid.';
    } else if (curMilestone.pay === 'tax_arrears') {
      paymentNote = 'Settle any outstanding MbPA property-tax arrears identified during assessment before filing. The amount is per municipal records and is not auto-calculated by this portal \u2014 enter the payment reference once settled.';
    }
  }

  return {
    reference: reference,
    applicantName: rec.applicantName || '',
    summary: rec.summary || '',
    filedDate: rec.dateStr || '',
    stage: stageLabel,
    stageIndex: cur.approverStep,   // legacy field name, now means "step within this milestone's chain"
    state: rec.state || 'under_scrutiny',
    officerRole: cur.role,
    officerName: cur.name,
    stepLabel: cur.label,
    stepIndex: cur.approverStep,
    stepTotal: cur.chainLen,
    replyExpectedDays: (rec.state === 'approved_final' || isAwaitingNext) ? 0 : remaining,
    slaDays: cur.slaDays,
    rejectedDocs: rec.rejectedDocs || [],
    rejectedReasons: rec.rejectedReasons || {},
    correctionDeadline: rec.correctionDeadline ? Utilities.formatDate(new Date(rec.correctionDeadline), Session.getScriptTimeZone() || 'Asia/Kolkata', 'dd MMM yyyy') : '',
    applicantComplaints: (rec.applicantComplaints || []).map(function (c) {
      return { at: c.at, items: c.items || [], details: c.details || '', stage: c.role, roleLabel: c.role || 'Officer' };
    }),
    pipeline: chain.map(function (st, i) {
      const stepNum = i + 1;
      let stt = 'pending';
      if (rec.state === 'approved_final') stt = 'done';
      else if (stepNum < cur.approverStep) stt = 'done';
      else if (stepNum === cur.approverStep) stt = (rec.state === 'rejected') ? 'returned' : (isAwaitingNext ? 'pending' : 'active');
      return { role: st.role, status: stt };
    }),
    // --- UPDR-2026 lifecycle (Pass 2, additive) ---
    stream: streamCfg.id,
    streamName: streamCfg.name,
    milestoneIdx: milestoneIdx,
    milestoneTotal: streamCfg.stages.length,
    milestoneName: curMilestone.name,
    milestoneOutput: curMilestone.milestone,
    milestonePay: curMilestone.pay,
    milestoneSlots: DOC_SLOTS[curMilestone.slots] || [],
    milestoneRoadmap: streamCfg.stages.map(function (s, i) {
      let stt2 = 'pending';
      if (i + 1 < milestoneIdx) stt2 = 'done';
      else if (i + 1 === milestoneIdx) stt2 = (rec.state === 'approved_final') ? 'done' : (isAwaitingNext ? 'awaiting' : 'active');
      return { idx: i + 1, name: s.name, output: s.milestone, status: stt2 };
    }),
    feeSnapshot: feeSnapshot,
    paymentNote: paymentNote,
    certificates: (rec.certificates || []).map(function (c) {
      const ms = streamCfg.stages.filter(function (x) { return x.id === c.milestone; })[0];
      return { kind: c.kind, name: c.name, url: c.url, at: c.at, label: ms ? ms.milestone : (c.kind === 'iod' ? 'Intimation of Disapproval' : c.name) };
    })
  };
}

/* ====================  APPLICANT COMPLAINT (against verifying officer)  ==================== */
// Role most recently acted on by an officer (approve/reject), falling back to whoever
// currently holds the file.
function lastActedRole_(rec) {
  const h = rec.history || [];
  for (let i = h.length - 1; i >= 0; i--) {
    if ((h[i].event === 'approved' || h[i].event === 'rejected') && h[i].role) return h[i].role;
  }
  return currentStep_(rec).role;
}

function raiseComplaint_(body) {
  const reference = sanitizeFile_(String(body.reference || '').toUpperCase().replace(/\s+/g, ''));
  const raw = CacheService.getScriptCache().get('otp_' + String(body.otpId));
  if (!raw) return { ok: false, error: 'Verification expired — please verify your status again.' };
  let v; try { v = JSON.parse(raw); } catch (e) { return { ok: false, error: 'Verification expired — please verify your status again.' }; }
  if (!v.verified) return { ok: false, error: 'Not verified.' };

  const rec = getApplication_(reference);
  if (!rec) return { ok: false, error: 'not_found' };
  if (String(v.email).toLowerCase() !== String(rec.email).toLowerCase())
    return { ok: false, error: 'Verification does not match this application.' };

  const items = Array.isArray(body.items) ? body.items.map(String).filter(Boolean).slice(0, 20) : [];
  const details = String(body.details || '').trim().slice(0, 2000);
  if (!items.length && !details) return { ok: false, error: 'Select at least one issue or describe what happened.' };

  const aboutRole = lastActedRole_(rec);
  const officer = OFFICER_BY_ROLE[aboutRole] || { role: aboutRole, email: '', name: aboutRole };
  const nowIso = new Date().toISOString();

  rec.applicantComplaints = rec.applicantComplaints || [];
  rec.applicantComplaints.push({ at: nowIso, role: aboutRole, items: items, details: details });
  rec.history.push({ at: nowIso, event: 'applicant_complaint', role: aboutRole, by: 'Applicant' });
  registerApplication_(reference, rec);

  safeMail_({ to: officer.email, name: SENDER_NAME,
    subject: 'Applicant complaint — ' + reference + ' (' + aboutRole + ')',
    htmlBody: applicantComplaintHtml_(reference, rec, officer, items, details) });
  safeMail_({ to: NOTIFY_TO, name: SENDER_NAME,
    subject: 'Applicant complaint logged — ' + reference + ' (' + aboutRole + ')',
    htmlBody: applicantComplaintHtml_(reference, rec, officer, items, details) });

  return { ok: true };
}
function getMyApplications_(body) {
  const sess = readToken_(body.token);
  const email = (sess && sess.email) || String(body.email || '').trim();
  if (!email) return { ok: true, items: [] };

  const items = [];
  const props = PropertiesService.getScriptProperties().getProperties();
  Object.keys(props).forEach(function (k) {
    if (k.indexOf('app_') !== 0) return;
    let rec; try { rec = JSON.parse(props[k]); } catch (e) { return; }
    if (!rec || String(rec.email).toLowerCase() !== email.toLowerCase()) return;
    const reference = k.slice(4);
    const cur = currentStep_(rec);
    const streamCfg = cur.streamCfg, milestoneIdx = cur.milestoneIdx, curMilestone = cur.milestone;
    items.push({
      reference: reference,
      name: 'Application_' + reference + '.pdf',
      dateStr: rec.dateStr || '',
      stage: cur.role,
      state: rec.state || 'under_scrutiny',
      url: rec.appFolderUrl || rec.folderUrl || '',
      streamName: streamCfg.name,
      milestoneIdx: milestoneIdx, milestoneTotal: streamCfg.stages.length,
      milestoneName: curMilestone.name, milestoneOutput: curMilestone.milestone
    });
  });
  items.sort(function (a, b) { return (a.dateStr < b.dateStr) ? 1 : -1; });
  return { ok: true, items: items.slice(0, 50) };
}

// Logged-in status lookup — bypasses the OTP challenge used by "Know your status" since the
// applicant is already authenticated. Used by the "My applications" list.
function myApplicationStatus_(body) {
  const sess = readToken_(body.token);
  if (!sess || sess.role !== 'applicant') return { ok: false, error: 'Session expired — please sign in again.' };
  const reference = sanitizeFile_(String(body.reference || '').toUpperCase().replace(/\s+/g, ''));
  const rec = getApplication_(reference);
  if (!rec) return { ok: false, error: 'not_found' };
  if (String(sess.email).toLowerCase() !== String(rec.email).toLowerCase())
    return { ok: false, error: 'This application is not registered to your account.' };
  return { ok: true, status: buildStatusView_(reference, rec) };
}

/* ============================  DOCUMENT FORMATS  ============================ */
function formatsInfo_(body) {
  try {
    const parent = DriveApp.getFolderById(PARENT_FOLDER_ID);
    const it = parent.getFilesByName(FORMATS_PDF_NAME);
    if (it.hasNext()) {
      const f = it.next();
      return { ok: true, available: true, name: f.getName(),
        base64: Utilities.base64Encode(f.getBlob().getBytes()) };
    }
  } catch (e) {}
  return { ok: true, available: false };
}

/* ============================  PERMIT COMPILER (storage)  ============================ */
// The PDF itself is built client-side (jsPDF, reusing the same navy/brass house style as the
// application form) — this endpoint just archives it under the application's Drive folder,
// logs it on the record, and emails it to the applicant.
function uploadCertificate_(body) {
  const s = requireOfficer_(body.token);
  if (!s) return { ok: false, error: 'Officer session expired.' };
  const reference = sanitizeFile_(String(body.reference || '').toUpperCase().replace(/\s+/g, ''));
  const rec = getApplication_(reference);
  if (!rec) return { ok: false, error: 'not_found' };
  if (!body.base64) return { ok: false, error: 'No file supplied.' };

  const kind = (String(body.kind || 'milestone') === 'iod') ? 'iod' : 'milestone';
  const milestoneId = String(body.milestoneId || '');
  const fileName = sanitizeFile_(body.fileName || (kind + '_' + reference + '.pdf'));

  let fileUrl = '';
  try {
    const folder = getRefFolder_(reference);
    const certFolder = getOrCreateChild_(folder, 'Certificates');
    const blob = Utilities.newBlob(Utilities.base64Decode(body.base64), 'application/pdf', fileName);
    const file = certFolder.createFile(blob);
    fileUrl = file.getUrl();

    rec.certificates = rec.certificates || [];
    rec.certificates.push({ kind: kind, milestone: milestoneId, name: fileName, url: fileUrl, fileId: file.getId(), at: new Date().toISOString() });
    registerApplication_(reference, rec);

    if (kind === 'iod') emailApplicantIod_(reference, rec, fileName, blob);
    else emailApplicantCertificate_(reference, rec, fileName, blob, milestoneId);
  } catch (err) {
    return { ok: false, error: String(err && err.message || err) };
  }
  return { ok: true, url: fileUrl };
}

/* ============================  FINAL DOSSIER COMPILER  ============================
   On final (Chairman) approval, the client merges these raw files into one PDF per group
   (jsPDF/pdf-lib, same engine the application-form merge already uses) and posts the results
   back via submitFinalDossier_ for archiving + a single consolidated email. This is ADDITIVE —
   the existing per-stage certificate email (uploadCertificate_) still fires exactly as before. */
function driveFileIdFromUrl_(url) {
  const m = String(url || '').match(/[-\w]{25,}/);
  return m ? m[0] : '';
}
function certFileId_(c) { return (c && (c.fileId || driveFileIdFromUrl_(c.url))) || ''; }
function latestCorrectedSubfolder_(baseFolder) {
  let latest = null, latestTime = 0;
  const subs = baseFolder.getFolders();
  while (subs.hasNext()) {
    const sub = subs.next();
    if (/^Corrected/i.test(sub.getName())) {
      const t = sub.getDateCreated().getTime();
      if (t > latestTime) { latestTime = t; latest = sub; }
    }
  }
  return latest;
}
function readFolderFilesB64_(folder, opts) {
  opts = opts || {};
  const out = [];
  const files = folder.getFiles();
  while (files.hasNext()) {
    const f = files.next();
    const name = f.getName();
    if (opts.onlyPdf && !/\.pdf$/i.test(name)) continue;
    const blob = f.getBlob();
    out.push({ name: name, mimeType: blob.getContentType() || 'application/octet-stream', base64: Utilities.base64Encode(blob.getBytes()) });
  }
  return out;
}
function getFinalDossier_(body) {
  const s = requireOfficer_(body.token);
  if (!s) return { ok: false, error: 'Officer session expired.' };
  const reference = sanitizeFile_(String(body.reference || '').toUpperCase().replace(/\s+/g, ''));
  const rec = getApplication_(reference);
  if (!rec) return { ok: false, error: 'not_found' };

  const folder = getRefFolder_(reference);

  // Stage 1 — the application itself: the single pre-merged PDF already produced at submission
  // (preferring the latest Corrected* resubmission, same rule officerOpen_ uses for scrutiny).
  let applicationFiles = [];
  try {
    const appFolder = getOrCreateChild_(folder, 'Application Document');
    const corrected = latestCorrectedSubfolder_(appFolder);
    applicationFiles = readFolderFilesB64_(corrected || appFolder, { onlyPdf: true });
  } catch (e) {}

  const certsByMilestone = {};
  (rec.certificates || []).forEach(function (c) {
    const fid = certFileId_(c); if (!fid) return;
    try {
      const f = DriveApp.getFileById(fid);
      const entry = { name: f.getName(), mimeType: 'application/pdf', base64: Utilities.base64Encode(f.getBlob().getBytes()) };
      const key = c.milestone || '';
      (certsByMilestone[key] = certsByMilestone[key] || []).push(entry);
    } catch (e) {}
  });

  const stageGroups = [];
  (rec.milestoneHistory || []).forEach(function (m, idx) {
    if (idx === 0) return; // stage 1 is applicationFiles above
    let docFiles = [];
    try {
      const msFolder = getOrCreateChild_(folder, 'Milestone ' + m.milestone + ' \u2014 ' + m.name);
      const corrected = latestCorrectedSubfolder_(msFolder);
      docFiles = readFolderFilesB64_(corrected || msFolder);
    } catch (e) {}
    stageGroups.push({ label: m.milestone + ' \u2014 ' + m.name, files: docFiles.concat(certsByMilestone[m.milestone] || []) });
  });

  const allCertificates = [];
  (rec.certificates || []).forEach(function (c) {
    const fid = certFileId_(c); if (!fid) return;
    try {
      const f = DriveApp.getFileById(fid);
      allCertificates.push({ name: f.getName(), mimeType: 'application/pdf', base64: Utilities.base64Encode(f.getBlob().getBytes()) });
    } catch (e) {}
  });

  return { ok: true, reference: reference,
    applicationGroup: { label: 'Application \u2014 Stage 1 (Ingestion & Verification)', files: applicationFiles },
    stageGroups: stageGroups, allCertificates: allCertificates };
}
function finalDossierEmailHtml_(reference, rec) {
  return shell_('Final approval \u2014 complete document dossier', 'Mumbai Port Authority \u00b7 Special Planning Authority',
    '<p style="margin:0 0 10px">Dear ' + esc_(rec.applicantName || 'Applicant') + ',</p>' +
    '<p style="margin:0 0 14px">Your application has received final approval. Attached is the complete document dossier for your records \u2014 the original application, the verified documents and certificate issued at every stage that was cleared, and a compiled set of all certificates.</p>' +
    '<table style="width:100%;border-collapse:collapse;font-size:13px">' + row_('Reference', reference) + row_('Status', 'Approved \u2014 final dossier issued') + '</table>' +
    statusBtn_());
}
function submitFinalDossier_(body) {
  const s = requireOfficer_(body.token);
  if (!s) return { ok: false, error: 'Officer session expired.' };
  const reference = sanitizeFile_(String(body.reference || '').toUpperCase().replace(/\s+/g, ''));
  const rec = getApplication_(reference);
  if (!rec) return { ok: false, error: 'not_found' };
  const files = Array.isArray(body.files) ? body.files : [];
  if (!files.length) return { ok: false, error: 'No dossier files supplied.' };

  const folder = getRefFolder_(reference);
  const dossierFolder = getOrCreateChild_(folder, 'Final Dossier');
  const attachments = [];
  files.forEach(function (f) {
    if (!f || !f.base64) return;
    const name = sanitizeFile_(f.name || 'Dossier.pdf');
    const blob = Utilities.newBlob(Utilities.base64Decode(f.base64), 'application/pdf', name);
    dossierFolder.createFile(blob.copyBlob());
    attachments.push(blob.copyBlob());
  });
  if (!attachments.length) return { ok: false, error: 'Could not archive any dossier file.' };

  rec.finalDossierSentAt = new Date().toISOString();
  registerApplication_(reference, rec);

  if (rec.email) {
    safeMail_({ to: rec.email, name: SENDER_NAME,
      subject: 'Final approval \u2014 complete document dossier \u2014 ' + reference + ' \u00b7 MbPA',
      htmlBody: finalDossierEmailHtml_(reference, rec), attachments: attachments });
  }
  return { ok: true, reference: reference, folderUrl: dossierFolder.getUrl() };
}

/* ============================  OFFICER ENDPOINTS  ============================ */
function requireOfficer_(token) {
  const s = readToken_(token);
  if (!s || s.role === 'applicant' || !OFFICER_BY_ROLE[s.role]) return null;
  return s;
}

function officerInbox_(body) {
  const s = requireOfficer_(body.token);
  if (!s) return { ok: false, error: 'Officer session expired — please sign in again.' };
  const myRole = s.role;

  const buckets = { toVerify: [], verified: [], rejected: [], complaint: [], appComplaint: [] };
  const props = PropertiesService.getScriptProperties().getProperties();
  Object.keys(props).forEach(function (k) {
    if (k.indexOf('app_') !== 0) return;
    let rec; try { rec = JSON.parse(props[k]); } catch (e) { return; }
    const reference = k.slice(4);
    const cur = currentStep_(rec);
    const remaining = slaRemaining_(rec, cur);
    const slaZone = remaining <= 0 ? 'red' : (remaining <= 2 ? 'amber' : 'green');
    const base = {
      reference: reference, applicantName: rec.applicantName || '', summary: rec.summary || '',
      filedDate: rec.dateStr || '', remainingDays: remaining, state: rec.state,
      slaZone: slaZone, milestoneIdx: cur.milestoneIdx, milestoneName: cur.milestone.name, milestoneTotal: cur.streamCfg.stages.length
    };

    // to-verify: under scrutiny at THIS officer's current step
    if (rec.state === 'under_scrutiny' && cur.role === myRole) buckets.toVerify.push(base);

    // verified by me: my role appears as an "approved" event in history
    const approvedByMe = (rec.history || []).some(function (h) { return h.event === 'approved' && h.role === myRole; });
    if (approvedByMe) buckets.verified.push(base);

    // rejected by me
    const rejectedByMe = (rec.history || []).some(function (h) { return h.event === 'rejected' && h.role === myRole; });
    if (rejectedByMe && rec.state === 'rejected') buckets.rejected.push(base);

    // complaint on me: SLA breach flagged against my role (system-raised)
    if ((rec.complaintAgainst || []).indexOf(myRole) !== -1) buckets.complaint.push(base);

    // complaint raised by the applicant against my role's verification
    if ((rec.applicantComplaints || []).some(function (c) { return c.role === myRole; })) buckets.appComplaint.push(base);
  });

  const sortFn = function (a, b) { return a.remainingDays - b.remainingDays; };
  buckets.toVerify.sort(sortFn);

  return { ok: true, role: myRole, buckets: buckets };
}

function officerOpen_(body) {
  const s = requireOfficer_(body.token);
  if (!s) return { ok: false, error: 'Officer session expired.' };
  const reference = sanitizeFile_(String(body.reference || '').toUpperCase().replace(/\s+/g, ''));
  const rec = getApplication_(reference);
  if (!rec) return { ok: false, error: 'not_found' };

  const streamCfg = streamById_(rec.stream);
  const milestoneIdx = rec.milestoneIdx || 1;
  const curMilestone = streamCfg.stages[milestoneIdx - 1] || streamCfg.stages[0];
  const isMilestone1 = milestoneIdx === 1;

  let pdfB64 = '', pdfName = '', docs = [], correctedFolderUrl = '';
  try {
    const folder = getRefFolder_(reference);
    const baseFolder = isMilestone1
      ? getOrCreateChild_(folder, 'Application Document')
      : getOrCreateChild_(folder, 'Milestone ' + curMilestone.id + ' \u2014 ' + curMilestone.name);

    if (isMilestone1) {
      const files = baseFolder.getFiles();
      while (files.hasNext()) {
        const f = files.next();
        if (/\.pdf$/i.test(f.getName())) { pdfB64 = Utilities.base64Encode(f.getBlob().getBytes()); pdfName = f.getName(); break; }
      }
    }

    // Prefer the MOST RECENT "Corrected*" subfolder when re-scrutinising after a rejection,
    // so the officer reviews the corrected files rather than the originals.
    let latestCorrected = null, latestTime = 0;
    const subs = baseFolder.getFolders();
    while (subs.hasNext()) {
      const sub = subs.next();
      if (/^Corrected/i.test(sub.getName())) {
        const t = sub.getDateCreated().getTime();
        if (t > latestTime) { latestTime = t; latestCorrected = sub; }
      }
    }
    const docSource = latestCorrected || (isMilestone1 ? getOrCreateChild_(folder, 'Uploaded Documents') : baseFolder);
    if (latestCorrected) correctedFolderUrl = latestCorrected.getUrl();
    const dfiles = docSource.getFiles();
    while (dfiles.hasNext()) { const f = dfiles.next(); docs.push({ name: f.getName(), url: f.getUrl() }); }
  } catch (e) {}

  return { ok: true,
    reference: reference,
    view: buildStatusView_(reference, rec),
    pdfName: pdfName, pdfBase64: pdfB64,
    documents: docs, folderUrl: rec.folderUrl || '',
    showingCorrected: !!correctedFolderUrl, correctedFolderUrl: correctedFolderUrl,
    milestoneIdx: milestoneIdx, milestoneName: curMilestone.name, milestoneOutput: curMilestone.milestone,
    milestoneTotal: streamCfg.stages.length, milestoneId: curMilestone.id, requiredSlots: DOC_SLOTS[curMilestone.slots] || [] };
}

function officerDecision_(body) {
  const s = requireOfficer_(body.token);
  if (!s) return { ok: false, error: 'Officer session expired.' };
  const reference = sanitizeFile_(String(body.reference || '').toUpperCase().replace(/\s+/g, ''));
  const rec = getApplication_(reference);
  if (!rec) return { ok: false, error: 'not_found' };

  const cur = currentStep_(rec);
  if (cur.role !== s.role || rec.state !== 'under_scrutiny')
    return { ok: false, error: 'This application is not currently at your stage.' };

  const nowIso = new Date().toISOString();
  const milestoneIdx = cur.milestoneIdx, curMilestone = cur.milestone;

  if (String(body.decision) === 'approve') {
    rec.history.push({ at: nowIso, event: 'approved', role: cur.role, by: cur.name, milestone: curMilestone.id, milestoneIdx: milestoneIdx, step: cur.approverStep });
    const t = advanceAfterApproval_(rec, cur, nowIso);
    registerApplication_(reference, rec);

    if (t.kind === 'stepAdvanced') {
      // officer-chain step WITHIN the same milestone (e.g. Estate Officer -> Junior Planner on S1).
      emailApplicantPromoted_(reference, rec, cur, t.next);
      notifyOfficerNew_(t.next, reference, rec);
      return { ok: true, reference: reference, state: rec.state, milestoneIdx: milestoneIdx, milestoneName: curMilestone.name };
    }
    if (t.kind === 'finalApproved') {
      emailApplicantApproved_(reference, rec);
      return { ok: true, reference: reference, state: rec.state, milestoneIdx: milestoneIdx,
        milestoneName: curMilestone.name, milestoneOutput: curMilestone.milestone, isFinalOverall: true };
    }
    // milestoneAdvanced — last officer in this milestone's chain cleared the WHOLE milestone.
    emailApplicantMilestoneApproved_(reference, rec, curMilestone, t.nextMilestone);
    return { ok: true, reference: reference, state: rec.state, milestoneIdx: milestoneIdx, milestoneAdvanced: true,
      milestoneName: curMilestone.name, milestoneOutput: curMilestone.milestone,
      nextMilestoneIdx: rec.milestoneIdx, nextMilestoneName: t.nextMilestone.name, nextMilestonePay: t.nextMilestone.pay };
  }

  if (String(body.decision) === 'reject') {
    const wrong = Array.isArray(body.wrongDocs) ? body.wrongDocs.filter(Boolean) : [];
    if (!wrong.length) return { ok: false, error: 'Select at least one document to be corrected.' };
    const reasonsIn = (body.reasons && typeof body.reasons === 'object') ? body.reasons : {};
    const reasons = {};
    wrong.forEach(function (name) { if (reasonsIn[name]) reasons[name] = String(reasonsIn[name]).slice(0, 600); });

    rec.state = 'rejected';
    rec.rejectedByRole = cur.role;
    rec.rejectedDocs = wrong;
    rec.rejectedReasons = reasons;
    rec.correctionDeadline = new Date(Date.now() + cur.slaDays * 864e5).toISOString();
    rec.history.push({ at: nowIso, event: 'rejected', role: cur.role, by: cur.name, docs: wrong, milestone: curMilestone.id, milestoneIdx: milestoneIdx });
    registerApplication_(reference, rec);
    emailApplicantRejected_(reference, rec, cur, wrong, reasons);
    return { ok: true, reference: reference, state: rec.state, milestoneIdx: milestoneIdx, milestoneName: curMilestone.name };
  }

  return { ok: false, error: 'Unknown decision.' };
}

/* ============================  SLA SWEEP (daily trigger)  ============================ */
function runSlaSweep() {
  const props = PropertiesService.getScriptProperties();
  const all = props.getProperties();
  const now = new Date();
  let promoted = 0, flagged = 0;

  Object.keys(all).forEach(function (k) {
    if (k.indexOf('app_') !== 0) return;
    let rec; try { rec = JSON.parse(all[k]); } catch (e) { return; }
    if (rec.state !== 'under_scrutiny') return;

    const reference = k.slice(4);
    const cur = currentStep_(rec);
    if (slaRemaining_(rec, cur, now) > 0) return;

    const nowIso = now.toISOString();

    // raise a complaint against the negligent officer's role
    rec.complaintAgainst = rec.complaintAgainst || [];
    if (rec.complaintAgainst.indexOf(cur.role) === -1) rec.complaintAgainst.push(cur.role);
    rec.history.push({ at: nowIso, event: 'sla_breach', role: cur.role, by: 'System' });

    if (cur.final && cur.isLastStepOfMilestone) {
      // Chairman on the final milestone (S7) is the terminus — cannot escalate further;
      // just keep the complaint flag and wait for an actual sign-off.
      rec.history.push({ at: nowIso, event: 'sla_chairman_flagged', role: cur.role, by: 'System' });
      registerApplication_(reference, rec);
      flagged++;
      return;
    }

    rec.history.push({ at: nowIso, event: 'sla_promoted', role: cur.role, by: 'System' });
    const t = advanceAfterApproval_(rec, cur, nowIso);
    registerApplication_(reference, rec);

    if (t.kind === 'stepAdvanced') {
      safeMail_({ to: rec.email, name: SENDER_NAME,
        subject: 'Application advanced — ' + reference, htmlBody: applicantPromotedHtml_(reference, rec, cur, t.next, true) });
      notifyOfficerNew_(t.next, reference, rec);
      safeMail_({ to: t.next.email, name: SENDER_NAME,
        subject: 'SLA escalation — ' + reference + ' (delay at ' + cur.role + ')',
        htmlBody: slaComplaintHtml_(reference, cur, t.next) });
    } else if (t.kind === 'milestoneAdvanced') {
      // last officer in the milestone's chain did not act — the milestone's output is treated
      // as granted (mirrors the old model's "Chairman SLA-breach" behaviour, generalised to
      // every milestone's last step rather than only the application's very last one).
      emailApplicantMilestoneApproved_(reference, rec, cur.milestone, t.nextMilestone);
    } else if (t.kind === 'finalApproved') {
      emailApplicantApproved_(reference, rec);
    }
    promoted++; flagged++;
  });
  Logger.log('SLA sweep: promoted=' + promoted + ' flagged=' + flagged);
}

/* ============================  FOLDERS  ============================ */
function ensureFolders_() { DriveApp.getFolderById(PARENT_FOLDER_ID).getName(); getCredentialsFolder_(); }
function getRefFolder_(reference) { return getOrCreateChild_(DriveApp.getFolderById(PARENT_FOLDER_ID), sanitizeFile_(reference)); }
function getCredentialsFolder_() { return getOrCreateChild_(DriveApp.getFolderById(PARENT_FOLDER_ID), '_credentials'); }
function getOrCreateChild_(parent, name) {
  const it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

/* ============================  APP REGISTRY  ============================ */
function registerApplication_(reference, obj) {
  PropertiesService.getScriptProperties().setProperty('app_' + reference, JSON.stringify(obj));
}
function getApplication_(reference) {
  const r = PropertiesService.getScriptProperties().getProperty('app_' + reference);
  return r ? JSON.parse(r) : null;
}
function refTxt_(reference, data, email) {
  return [
    'MUMBAI PORT AUTHORITY — Special Planning Authority',
    'Building Permission Portal (UPDR-2026)', '',
    'Application number : ' + reference,
    'Applicant          : ' + (data.applicantName || '-'),
    'Registered email   : ' + email,
    'Mobile             : ' + (data.phone || '-'),
    'Parcel / summary   : ' + (data.summary || '-'),
    'Filed              : ' + (data.dateStr || today_()),
    'Filed at           : ' + (data.submittedAt || new Date().toISOString()),
    'Status             : Filed — under scrutiny (Estate Officer)'
  ].join('\n');
}

/* ============================  SHARED HELPERS  ============================ */
function sixDigit_() { return String(Math.floor(100000 + Math.random() * 900000)); }
function digits_(s) { return String(s || '').replace(/\D/g, ''); }
function sanitizeFile_(s) { return String(s || '').replace(/[\\\/:*?"<>|]+/g, '_').replace(/\s+/g, ' ').trim().slice(0, 120); }
function today_() { return Utilities.formatDate(new Date(), Session.getScriptTimeZone() || 'Asia/Kolkata', 'yyyy-MM-dd'); }
function esc_(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function maskEmail_(email) {
  const s = String(email || ''); const at = s.indexOf('@');
  if (at < 1) return s;
  const name = s.slice(0, at), dom = s.slice(at);
  if (name.length <= 2) return name[0] + '•••' + dom;
  return name[0] + '••••' + name[name.length - 1] + dom;
}
// working days (excl Sat/Sun) strictly between two dates, counting whole elapsed days
function workingDaysBetween_(from, to) {
  if (!(from instanceof Date) || isNaN(from)) return 0;
  let count = 0;
  const d = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  const end = new Date(to.getFullYear(), to.getMonth(), to.getDate());
  while (d < end) {
    d.setDate(d.getDate() + 1);
    const day = d.getDay();
    if (day !== 0 && day !== 6) count++;
  }
  return count;
}

/* ============================  E-MAIL TEMPLATES  ============================ */
function shell_(headerTitle, headerSub, bodyHtml) {
  return '' +
  '<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:auto;border:1px solid #dde5ee;border-radius:12px;overflow:hidden">' +
    '<div style="background:#0a2540;color:#fff;padding:18px 22px">' +
      '<div style="font-size:16px;font-weight:700">' + esc_(headerTitle) + '</div>' +
      '<div style="font-size:12px;color:#cdd9e6">' + esc_(headerSub) + '</div>' +
    '</div>' +
    '<div style="padding:22px;color:#0c1a2b;font-size:14px;line-height:1.6">' + bodyHtml + '</div>' +
  '</div>';
}
function statusBtn_() {
  return '<div style="margin:20px 0 4px"><a href="' + STATUS_LINK + '" ' +
    'style="display:inline-block;background:#0e7c86;color:#fff;text-decoration:none;font-weight:700;' +
    'padding:11px 18px;border-radius:8px;font-size:13px">Verify your status</a></div>' +
    '<div style="font-size:12px;color:#6b819a;margin-top:8px">Or visit ' + STATUS_LINK + '</div>';
}
function row_(k, v) {
  return '<tr><td style="padding:5px 14px 5px 0;color:#6b819a;vertical-align:top">' + esc_(k) +
         '</td><td style="padding:5px 0;font-weight:600">' + esc_(v || '—') + '</td></tr>';
}
function otpEmailHtml_(code) {
  return shell_('Mumbai Port Authority', 'Special Planning Authority · Building Permission Portal',
    '<p style="margin:0 0 14px">Use this one-time code to continue:</p>' +
    '<div style="font-size:30px;font-weight:800;letter-spacing:8px;color:#004C93;text-align:center;background:#e9f1f9;border:1px solid #bcd5ec;border-radius:10px;padding:14px 0">' + esc_(code) + '</div>' +
    '<p style="margin:16px 0 0;font-size:12.5px;color:#6b819a">This code expires in 10 minutes. If you did not request it, ignore this email.</p>');
}
function securityAlertHtml_() {
  return shell_('Security alert', 'Mumbai Port Authority · Special Planning Authority',
    '<p style="margin:0 0 12px">We received a request to create a <b>new portal account using your Aadhaar number</b>.</p>' +
    '<p style="margin:0 0 12px">An Aadhaar number can be linked to only one account, so this attempt was <b>blocked</b>. ' +
    'If this was you, please sign in to your existing account instead. If it was not you, no action is needed — your account is safe.</p>');
}
function ackEmailHtml_(d) {
  return shell_('Application received', 'Mumbai Port Authority · Special Planning Authority',
    '<p style="margin:0 0 10px">Dear ' + esc_(d.applicantName || 'Applicant') + ',</p>' +
    '<p style="margin:0 0 14px">Your building-permission application has been received and recorded under the reference below. A copy of the application form is attached as a PDF. It will first be scrutinised by the <b>Estate Officer</b>.</p>' +
    '<table style="width:100%;border-collapse:collapse;font-size:13px">' +
      row_('Reference', d.reference) + row_('Parcel (PLPN)', d.summary) + row_('Filed', d.dateStr) +
    '</table>' + statusBtn_());
}
function intakeEmailHtml_(d, folderUrl) {
  return '<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#0c1a2b">' +
    '<h3 style="margin:0 0 8px;color:#0a2540">New building-permission application</h3>' +
    '<table style="border-collapse:collapse">' +
      row_('Reference', d.reference) + row_('Applicant', d.applicantName) + row_('Email', d.email) +
      row_('Mobile', d.phone) + row_('Professional', d.professionalName) + row_('Summary', d.summary) +
      row_('Drive folder', folderUrl) +
    '</table></div>';
}
function notifyOfficerNew_(stage, reference, rec) {
  safeMail_({ to: stage.email, name: SENDER_NAME,
    subject: 'Application awaiting your scrutiny — ' + reference + ' (' + stage.role + ')',
    htmlBody: shell_('Application awaiting scrutiny', 'Mumbai Port Authority · ' + stage.role,
      '<p style="margin:0 0 10px">Dear ' + esc_(stage.name) + ',</p>' +
      '<p style="margin:0 0 14px">A building-permission application is awaiting your scrutiny' +
        (stage.label ? ' (<b>' + esc_(stage.label) + '</b>)' : '') + '. You have <b>' + (stage.slaDays || DEFAULT_SLA_DAYS) + ' working days</b> to take action, after which it is escalated automatically.</p>' +
      '<table style="width:100%;border-collapse:collapse;font-size:13px">' +
        row_('Reference', reference) + row_('Applicant', rec.applicantName) + row_('Parcel', rec.summary) +
      '</table>' +
      '<p style="margin:16px 0 0;font-size:12.5px;color:#6b819a">Sign in to the portal to review the documents and approve or return the application.</p>') });
}
function officerCorrectedHtml_(reference, rec, folderUrl) {
  return shell_('Corrected documents received', 'Mumbai Port Authority',
    '<p style="margin:0 0 12px">The applicant for <b>' + esc_(reference) + '</b> has uploaded corrected documents, which are now awaiting your re-scrutiny.</p>' +
    '<table style="width:100%;border-collapse:collapse;font-size:13px">' +
      row_('Reference', reference) + row_('Applicant', rec.applicantName) + row_('Corrected files', folderUrl) +
    '</table>');
}
function emailApplicantPromoted_(reference, rec, fromStage, toStage) {
  safeMail_({ to: rec.email, name: SENDER_NAME,
    subject: 'Application promoted to the next stage — ' + reference,
    htmlBody: applicantPromotedHtml_(reference, rec, fromStage, toStage, false) });
}
function applicantPromotedHtml_(reference, rec, fromStage, toStage, bySla) {
  const lead = bySla
    ? 'On review of timelines, your application has been <b>advanced to the next stage of scrutiny</b> to keep it moving without delay.'
    : 'We are pleased to inform you that your application has cleared scrutiny by the <b>' + esc_(fromStage.role) + '</b> and has been <b>promoted to the next stage</b>.';
  return shell_('Application progress update', 'Mumbai Port Authority · Special Planning Authority',
    '<p style="margin:0 0 10px">Dear ' + esc_(rec.applicantName || 'Applicant') + ',</p>' +
    '<p style="margin:0 0 14px">' + lead + '</p>' +
    '<table style="width:100%;border-collapse:collapse;font-size:13px">' +
      row_('Reference', reference) + row_('Now with', toStage.role) +
      row_('Expected action within', (toStage.slaDays || DEFAULT_SLA_DAYS) + ' working days') +
    '</table>' + statusBtn_());
}
function emailApplicantRejected_(reference, rec, stage, wrongDocs, reasons) {
  reasons = reasons || {};
  const items = '<ul style="margin:8px 0 0;padding-left:18px">' + wrongDocs.map(function (d) {
    const r = reasons[d];
    return '<li style="margin:3px 0">' + esc_(d) + (r ? '<br><span style="color:#6b819a;font-size:12px">Reason: ' + esc_(r) + '</span>' : '') + '</li>'; }).join('') + '</ul>';
  safeMail_({ to: rec.email, name: SENDER_NAME,
    subject: 'Action required — your application has been returned for correction (' + reference + ')',
    htmlBody: shell_('Application returned for correction', 'Mumbai Port Authority · Special Planning Authority',
      '<p style="margin:0 0 10px">Dear ' + esc_(rec.applicantName || 'Applicant') + ',</p>' +
      '<p style="margin:0 0 12px">On scrutiny by the <b>' + esc_(stage.role) + '</b>, your application has been <b>placed on hold</b> because one or more submitted documents require correction. Kindly review the items below and re-upload the corrected documents.</p>' +
      '<div style="background:#fbf0db;border:1px solid #eed29a;border-radius:8px;padding:12px 14px">' +
        '<div style="font-weight:700;color:#9a5b07">Documents to be corrected</div>' + items +
      '</div>' +
      '<p style="margin:14px 0 0;font-size:13px">You have <b>' + (stage.slaDays || DEFAULT_SLA_DAYS) + ' working days</b> to upload the corrected documents through the portal. The full details are available on your status page.</p>' +
      statusBtn_()) });
}
function emailApplicantApproved_(reference, rec) {
  // attach the merged application PDF (and serve as the "approval" copy)
  let attachments = [];
  try {
    const folder = getRefFolder_(reference);
    const appFolder = getOrCreateChild_(folder, 'Application Document');
    const files = appFolder.getFiles();
    while (files.hasNext()) { const f = files.next(); if (/\.pdf$/i.test(f.getName())) { attachments.push(f.getBlob()); break; } }
  } catch (e) {}
  safeMail_({ to: rec.email, name: SENDER_NAME,
    subject: 'Approved — building permission granted (' + reference + ')',
    htmlBody: shell_('Building permission approved', 'Mumbai Port Authority · Special Planning Authority',
      '<p style="margin:0 0 10px">Dear ' + esc_(rec.applicantName || 'Applicant') + ',</p>' +
      '<p style="margin:0 0 14px">We are pleased to inform you that your building-permission application has been <b>approved by the Chairman</b> and is granted under the Unified Planning and Development Regulations, 2026. The approved application is attached for your records.</p>' +
      '<table style="width:100%;border-collapse:collapse;font-size:13px">' +
        row_('Reference', reference) + row_('Status', 'Approved') +
      '</table>' + statusBtn_()),
    attachments: attachments });
}
function emailApplicantMilestoneApproved_(reference, rec, fromMilestone, toMilestone) {
  const payNote = toMilestone.pay !== 'none'
    ? '<p style="margin:0 0 12px">The next stage has a payment touchpoint. Sign in to the portal, open this application, and use <b>File next stage</b> to view the amount due, settle it, and upload the required documents.</p>'
    : '<p style="margin:0 0 12px">Sign in to the portal, open this application, and use <b>File next stage</b> to upload the documents required for the next stage.</p>';
  safeMail_({ to: rec.email, name: SENDER_NAME,
    subject: 'Stage cleared — ' + fromMilestone.name + ' (' + reference + ')',
    htmlBody: shell_('Stage cleared', 'Mumbai Port Authority · Special Planning Authority',
      '<p style="margin:0 0 10px">Dear ' + esc_(rec.applicantName || 'Applicant') + ',</p>' +
      '<p style="margin:0 0 14px">Your application has cleared <b>' + esc_(fromMilestone.name) + '</b>. Output granted: <b>' + esc_(fromMilestone.milestone) + '</b>.</p>' +
      '<table style="width:100%;border-collapse:collapse;font-size:13px">' +
        row_('Reference', reference) + row_('Next stage', toMilestone.name) +
      '</table>' + payNote + statusBtn_()) });
}
function emailApplicantCertificate_(reference, rec, fileName, blob, milestoneId) {
  const streamCfg = streamById_(rec.stream);
  const ms = streamCfg.stages.filter(function (x) { return x.id === milestoneId; })[0];
  const label = ms ? ms.milestone : 'Stage certificate';
  safeMail_({ to: rec.email, name: SENDER_NAME,
    subject: 'Certificate issued — ' + label + ' (' + reference + ')',
    htmlBody: shell_('Certificate issued', 'Mumbai Port Authority · Special Planning Authority',
      '<p style="margin:0 0 10px">Dear ' + esc_(rec.applicantName || 'Applicant') + ',</p>' +
      '<p style="margin:0 0 14px">The certificate for <b>' + esc_(label) + '</b> has been issued and is attached, bearing the official MbPA seal.</p>' +
      '<table style="width:100%;border-collapse:collapse;font-size:13px">' + row_('Reference', reference) + row_('Document', fileName) + '</table>' + statusBtn_()),
    attachments: [blob.copyBlob().setName(fileName)] });
}
function emailApplicantIod_(reference, rec, fileName, blob) {
  safeMail_({ to: rec.email, name: SENDER_NAME,
    subject: 'Intimation of Disapproval — ' + reference,
    htmlBody: shell_('Intimation of Disapproval (IOD)', 'Mumbai Port Authority · Special Planning Authority',
      '<p style="margin:0 0 10px">Dear ' + esc_(rec.applicantName || 'Applicant') + ',</p>' +
      '<p style="margin:0 0 14px">The formal Intimation of Disapproval for this application is attached, listing the deficiencies to be corrected.</p>' +
      '<table style="width:100%;border-collapse:collapse;font-size:13px">' + row_('Reference', reference) + row_('Document', fileName) + '</table>' + statusBtn_()),
    attachments: [blob.copyBlob().setName(fileName)] });
}
function slaComplaintHtml_(reference, fromStage, toStage) {
  return shell_('SLA escalation notice', 'Mumbai Port Authority',
    '<p style="margin:0 0 12px">Application <b>' + esc_(reference) + '</b> was not actioned within the ' + (fromStage.slaDays || DEFAULT_SLA_DAYS) + '-working-day window at the <b>' + esc_(fromStage.role) + '</b> stage.</p>' +
    '<p style="margin:0 0 12px">It has been escalated to you (<b>' + esc_(toStage.role) + '</b>) and a complaint has been recorded against the ' + esc_(fromStage.role) + ' for the delay. Please prioritise this file.</p>');
}
function applicantComplaintHtml_(reference, rec, stage, items, details) {
  const list = items.length
    ? '<ul style="margin:8px 0 0;padding-left:18px">' + items.map(function (i) { return '<li style="margin:3px 0">' + esc_(i) + '</li>'; }).join('') + '</ul>'
    : '<p style="margin:6px 0 0;color:#6b819a">No checklist items selected.</p>';
  return shell_('Applicant complaint received', 'Mumbai Port Authority · ' + stage.role,
    '<p style="margin:0 0 10px">Dear ' + esc_(stage.name) + ',</p>' +
    '<p style="margin:0 0 12px">The applicant for <b>' + esc_(reference) + '</b> has raised a complaint about document verification at your stage. This is logged against the application; no action is forced, but please review.</p>' +
    '<table style="width:100%;border-collapse:collapse;font-size:13px">' +
      row_('Reference', reference) + row_('Applicant', rec.applicantName) + row_('Stage concerned', stage.role) +
    '</table>' +
    '<div style="background:#fcebe9;border:1px solid #f3c4bf;border-radius:8px;padding:12px 14px;margin-top:14px">' +
      '<div style="font-weight:700;color:#b42318">Issues raised</div>' + list +
    '</div>' +
    (details ? '<div style="margin-top:12px"><div style="font-weight:700;color:#143a60">Applicant\u2019s description</div><p style="margin:6px 0 0;white-space:pre-wrap">' + esc_(details) + '</p></div>' : ''));
}

/* ====================================================================
   UPDR-2026  ·  STREAM · LIFECYCLE · DOC-SLOT · FEE CONFIGURATION
   Added Pass 1 (additive). Source: MbPA EODB framework §1–§4.
   No fee value is invented: the ₹/m² rates and premium coefficients are
   taken verbatim from the framework. Zonal RRR ships EMPTY and must be
   supplied per parcel from MbPA's official Ready Reckoner.
   This block is read by getStreamConfig_ / calcFees_ only — it does not
   touch the existing submission, officer or SLA code paths.
   ==================================================================== */

const FEE_RULES = {
  perSqm:      { scrutiny: 50, security: 10, debris: 20 },        // ₹ per m² of proposed BUA
  premiumCoef: { fsi: 1.10, openSpace: 0.25, parking: 0.40 },     // C_prem by concession category
  refundable:  ['security', 'debris']
};

const DOC_SLOTS = {
  S1: ['Lease Deed / Allotment Letter (executed copy)',
       'Site Plan / Key Plan (lat\u2013long verified by authorised consultant)',
       'Preliminary Architectural Layout (setbacks + building height)',
       'MCZMA CRZ Certificate \u2014 conditional (only if plot intersects CRZ)',
       'Form 6 \u2014 Registered Developer Undertaking'],
  S2: ['Form 4A \u2014 Project Fact Sheet',
       'Form 4B \u2014 Design Scrutiny Register',
       'Structural Design & Stability Certificate (Reg. Structural Engineer)',
       'Advocate Certified Title Clearance Certificate',
       'Co-owner / Tenant Consent (\u226570% where applicable)',
       'Form 7 \u2014 Structural & Civil Liability Indemnity Bond',
       'CFO Pre-Sanction NOC',
       'Tree Authority Clearance',
       'Water Availability NOC',
       'Storm-Water Drain (SWD) remarks'],
  S3: ['Annexure-10 \u2014 Intimation of Plinth Completion (Architect signed)',
       'Geotagged plinth photographs (combined into a single PDF)',
       'Structural Engineer Validation Certificate'],
  S4: ['Tranche application \u2014 slab levels + cumulative BUA',
       'Structural interim stability tracking logs',
       'MoEFCC Environmental Clearance \u2014 conditional (BUA > 20,000 m\u00b2)',
       'DGCA / AAI Aviation Height Clearance \u2014 conditional',
       'High-Rise Committee (HRC) Clearance \u2014 conditional (height > 70 m)'],
  S5: ['Tranche application \u2014 final slab levels + cumulative BUA',
       'Structural interim stability tracking logs'],
  S6: ['Annexure-13 \u2014 Drainage Completion Certificate (licensed plumber)',
       'Annexure-12 \u2014 Development & Building Completion Certificate (Architect / PoR)',
       'Final CFO Completion Remarks',
       'Tree Authority compliance certification',
       'Service consultant completion sheets (HVAC / Electrical / Mechanical / RWH)'],
  S7: ['Annexure-14 \u2014 Application for Occupancy Certificate',
       'Verified DCC + BCC (from Stage 6)',
       'Latest paid MbPA Property Tax Receipt',
       'Handover of public reservations / amenities (if applicable)'],
  DEMO: ['Tenant Vacation Certificate',
         'CFO Demolition NOC',
         'Debris Management Plan']
};

// Canonical New-Building 7-stage lifecycle (the structural baseline, framework §1).
const NB_STAGES = [
  { id:'S1', name:'Ingestion & Verification',                 milestone:'Approval in Principle (AIP) \u2014 valid 2 years',         slots:'S1', pay:'none',           sla:'Triage 3 wd \u00b7 Estate NOC + AIP 21 wd combined' },
  { id:'S2', name:'Design Sanction & Foundation Clearance',    milestone:'Development Permission (5 yr) + CC to plinth',           slots:'S2', pay:'master_challan', sla:'30-day statutory clock \u00b7 scrutiny 21 d' },
  { id:'S3', name:'Sub-Structure Validation',                 milestone:'Annexure-11 \u2014 Further CC (superstructure)',           slots:'S3', pay:'infra_utility',  sla:'Field inspection 5 wd \u00b7 Further CC 7 d' },
  { id:'S4', name:'Superstructure \u2014 80% BUA',             milestone:'80% BUA Commencement Certificate',                       slots:'S4', pay:'none',           sla:'Site validation 7 d \u00b7 CC 7\u201315 wd' },
  { id:'S5', name:'Superstructure \u2014 Remaining 20% BUA',   milestone:'Remaining 20% BUA Commencement Certificate',             slots:'S5', pay:'none',           sla:'Site validation 7 d \u00b7 CC 7\u201315 wd' },
  { id:'S6', name:'Service Infrastructure Integration',       milestone:'Building Completion Certificate (BCC)',                  slots:'S6', pay:'none',           sla:'Review + survey 7 d \u00b7 acceptance 7 d' },
  { id:'S7', name:'Statutory Finalization',                   milestone:'Occupancy Certificate (OC)',                             slots:'S7', pay:'tax_arrears',    sla:'Triage 3 wd \u00b7 joint inspection 10 d \u00b7 OC 15 wd' }
];

// 7 regulatory streams (framework §1 baseline + §2 quick-route matrix).
const STREAMS = [
  { id:'new',        name:'New Building (Full Lifecycle)',            stageCount:7, rule:'Structural baseline \u2014 all seven statutory milestones.',                                                              stages: NB_STAGES },
  { id:'addition',   name:'Addition / Alteration',                   stageCount:5, rule:'If modifications exceed 50% of original BUA, the file auto-converts to a New Building lifecycle.',                      stages: subStages_(['S1','S2','S3','S6','S7']) },
  { id:'layout',     name:'Layout / Sub-division / Amalgamation',    stageCount:5, rule:'All internal infrastructure must be certified complete before OC is permitted for any area exceeding 90% of layout BUA.', stages: subStages_(['S1','S2','S3','S6','S7']) },
  { id:'reerection', name:'Re-erection',                             stageCount:8, rule:'Building-permission intake is blocked until an MbPA inspector certifies the site clear and vacant (Demolition + full cycle).', stages: [demoStage_()].concat(NB_STAGES) },
  { id:'temporary',  name:'Temporary Permission',                    stageCount:4, rule:'Hard 3-year expiry. Permanent foundations / underground works are blocked.',                                            stages: subStages_(['S1','S2','S6','S7']) },
  { id:'special',    name:'Special Buildings (High-Rise / Hazardous)', stageCount:7, rule:'Mandatory CFO site inspection before any CC tranche above 70 m structural height.',                                  stages: NB_STAGES },
  { id:'regularise', name:'Regularisation of Unauthorised Construction', stageCount:6, rule:'Auto-blocked if coordinates intersect CRZ, operational port zones, or heritage buffers.',                          stages: subStages_(['S1','S2','S3','S4','S6','S7']) }
];

function subStages_(ids){
  return ids.map(function (id) { return NB_STAGES.filter(function (s) { return s.id === id; })[0]; }).filter(Boolean);
}
function demoStage_(){
  return { id:'DEMO', name:'Demolition & Site Clearance', milestone:'Site Clearance Certificate (inspector verified)', slots:'DEMO', pay:'none', sla:'Inspector site-clear certification' };
}

// Zonal Ready Reckoner Rate (\u20b9/m\u00b2). Intentionally EMPTY \u2014 populate from MbPA's
// official Ready Reckoner per port zone. No value is invented here.
const ZONAL_RRR = {};   // e.g. { 'Mazgaon': 0, 'Sewri': 0 }

function streamConfig_(){
  return { streams: STREAMS, docSlots: DOC_SLOTS, feeRules: FEE_RULES, zonalRRR: ZONAL_RRR };
}
function getStreamConfig_(body){ return { ok: true, config: streamConfig_() }; }

// Centralized billing module (framework §3). Accepts EITHER a single
// {concession, deltaArea} pair (Pass-1 Planner shape) OR a {concessions:[{kind,deltaArea}]}
// array (real intake can trigger several deficiencies at once). Both are summed
// identically; the single-pair shape is normalised into a one-item array.
function calcFees_(body){
  var bua = Number(body.bua || 0);
  var rrr = Number(body.rrr || 0);
  if (!(bua >= 0)) return { ok: false, error: 'Proposed BUA must be a non-negative number.' };

  var items = Array.isArray(body.concessions) ? body.concessions : [];
  if (!items.length && body.concession) {
    items = [{ kind: String(body.concession), deltaArea: Number(body.deltaArea || 0) }];
  }

  var scrutiny = bua * FEE_RULES.perSqm.scrutiny;
  var security = bua * FEE_RULES.perSqm.security;
  var debris   = bua * FEE_RULES.perSqm.debris;

  var premium = 0, premiumItems = [];
  items.forEach(function (it) {
    var kind = String((it && it.kind) || '');
    var dA   = Number((it && it.deltaArea) || 0);
    var coef = FEE_RULES.premiumCoef[kind] || 0;
    var fee  = (dA > 0 && coef > 0) ? dA * rrr * coef : 0;
    premium += fee;
    premiumItems.push({ kind: kind, deltaArea: dA, premiumCoef: coef, fee: Math.round(fee) });
  });

  var total = scrutiny + security + debris + premium;
  return { ok: true, fees: {
    scrutiny: Math.round(scrutiny), security: Math.round(security), debris: Math.round(debris),
    premium: Math.round(premium), masterChallanTotal: Math.round(total),
    items: premiumItems,
    premiumCoef: premiumItems.length ? premiumItems[0].premiumCoef : 0,   // back-compat single value
    refundable: FEE_RULES.refundable
  }};
}

// Resolve a stream id to its config; unknown/missing ids fall back to STREAMS[0] ('new'),
// which is the safe default for any application predating stream selection.
function streamById_(id) {
  var found = STREAMS.filter(function (s) { return s.id === String(id || ''); })[0];
  return found || STREAMS[0];
}
