import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import {
  ShieldCheck, ShieldAlert, ShieldX,
  ChevronDown, ChevronUp, Copy, Check,
  RotateCcw, AlertTriangle, ExternalLink,
  CheckCircle2, Info, MessageCircle
} from 'lucide-react'
import './VerdictPage.css'

const VERDICT_CONFIG = {
  SAFE:   { label: 'Safe to Pay',  Icon: ShieldCheck, color: 'var(--safe)',   bg: 'rgba(16,185,129,0.08)',  border: 'rgba(16,185,129,0.2)',  gradient: 'linear-gradient(135deg,rgba(16,185,129,0.12) 0%,transparent 60%)',   emoji: '🟢' },
  VERIFY: { label: 'Verify First', Icon: ShieldAlert, color: 'var(--verify)', bg: 'rgba(245,158,11,0.08)',  border: 'rgba(245,158,11,0.2)',  gradient: 'linear-gradient(135deg,rgba(245,158,11,0.12) 0%,transparent 60%)',  emoji: '🟡' },
  DANGER: { label: 'DO NOT PAY',   Icon: ShieldX,     color: 'var(--danger)', bg: 'rgba(239,68,68,0.08)',   border: 'rgba(239,68,68,0.2)',   gradient: 'linear-gradient(135deg,rgba(239,68,68,0.15) 0%,transparent 60%)',    emoji: '🔴' },
}

const AGENT_NAMES = {
  destination_intelligence: { name: 'Destination Intelligence', model: 'Featherless AI',        emoji: '🔍' },
  qr_upi_validator:         { name: 'QR & UPI Validator',        model: 'AIML API Vision',       emoji: '📷' },
  web_intelligence:         { name: 'Web Intelligence',           model: 'Playwright + Search',   emoji: '🌐' },
}

function RiskRing({ score, color }) {
  const radius = 52
  const circ = 2 * Math.PI * radius
  const [offset, setOffset] = useState(circ)
  useEffect(() => {
    const t = setTimeout(() => setOffset(circ - (score / 100) * circ), 400)
    return () => clearTimeout(t)
  }, [score, circ])
  return (
    <svg className="risk-ring" viewBox="0 0 120 120" width="120" height="120">
      <circle cx="60" cy="60" r={radius} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10"/>
      <circle cx="60" cy="60" r={radius} fill="none" stroke={color} strokeWidth="10"
        strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={offset}
        transform="rotate(-90 60 60)"
        style={{ transition:'stroke-dashoffset 1.2s cubic-bezier(0.4,0,0.2,1)', filter:`drop-shadow(0 0 8px ${color})` }}
      />
      <text x="60" y="58" textAnchor="middle" dominantBaseline="middle" fontSize="22" fontWeight="800" fill={color}>{score}</text>
      <text x="60" y="76" textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.4)">/ 100</text>
    </svg>
  )
}

function AccordionCard({ emoji, name, model, narrative, priceIntel }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="accordion-card glass">
      <button className="accordion-toggle" onClick={() => setOpen(o => !o)}>
        <div className="accordion-left">
          <span className="acc-emoji">{emoji}</span>
          <div>
            <div className="acc-name">{name}</div>
            <div className="acc-model">{model}</div>
          </div>
        </div>
        {open ? <ChevronUp size={16}/> : <ChevronDown size={16}/>}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div className="accordion-body"
            initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }}>
            <p className="acc-narrative">{narrative || 'No narrative available.'}</p>
            {priceIntel && (
              <div className="price-intel-box">
                <div className="price-intel-header"><Info size={14}/> Price Intelligence</div>
                <div className="price-intel-data">
                  {priceIntel.market_price_range && (
                    <div className="price-row"><span>Market Price Range</span><span className="price-value">{priceIntel.market_price_range}</span></div>
                  )}
                  {priceIntel.requested_amount && (
                    <div className="price-row"><span>Amount Requested</span>
                      <span className={`price-value ${priceIntel.anomaly_detected ? 'price-danger' : 'price-safe'}`}>
                        ₹{Number(priceIntel.requested_amount).toLocaleString('en-IN')}
                      </span>
                    </div>
                  )}
                  {priceIntel.anomaly_detected !== undefined && (
                    <div className={`price-indicator ${priceIntel.anomaly_detected ? 'danger' : 'safe'}`}>
                      {priceIntel.anomaly_detected ? '⚠ Price anomaly detected' : '✓ Price within market range'}
                    </div>
                  )}
                  {priceIntel.notes && <p className="price-notes">{priceIntel.notes}</p>}
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function SkeletonLoader() {
  return (
    <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
      {[220,100,100,80].map((h,i) => (
        <div key={i} className="skeleton" style={{ height: h, borderRadius: 16 }}/>
      ))}
    </div>
  )
}

export default function VerdictPage() {
  const { txn_id } = useParams()
  const navigate = useNavigate()
  const [report, setReport]         = useState(null)
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [copied, setCopied]         = useState(false)
  const [overrideInput, setOverride] = useState('')

  useEffect(() => {
    let attempts = 0
    const MAX = 40
    async function fetchReport() {
      while (attempts < MAX) {
        try {
          const res = await axios.get(`/api/report/${txn_id}`)
          if (res.status === 200 && res.data.verdict) { setReport(res.data); setLoading(false); return }
          if (res.status === 202) { await sleep(2000); attempts++; continue }
        } catch (err) {
          if (err.response?.status === 202) { await sleep(2000); attempts++; continue }
          setError(err.response?.data?.detail || err.message); setLoading(false); return
        }
        attempts++
      }
      setError('Report took too long. Please refresh.'); setLoading(false)
    }
    fetchReport()
  }, [txn_id])

  function copyReport() {
    navigator.clipboard.writeText(`${window.location.origin}/report/${txn_id}`)
    setCopied(true); setTimeout(() => setCopied(false), 2000)
  }

  if (loading) return <div className="verdict-page"><div className="verdict-container"><SkeletonLoader/></div></div>
  if (error) return (
    <div className="verdict-page"><div className="verdict-container">
      <div className="glass error-state">
        <AlertTriangle size={32} className="error-icon"/>
        <h2>Could not load report</h2>
        <p>{error}</p>
        <button className="btn-primary" onClick={() => navigate('/')}>Go Home</button>
      </div>
    </div></div>
  )

  const vc = VERDICT_CONFIG[report.verdict] || VERDICT_CONFIG.VERIFY
  const { Icon: VIcon } = vc
  const narratives = report.agent_narratives || {}
  const isDanger = report.verdict === 'DANGER'
  const isVerify = report.verdict === 'VERIFY'
  const canOverride = overrideInput.trim() === 'I UNDERSTAND THE RISK'

  return (
    <div className="verdict-page">
      <div className="verdict-container">

        {/* Hero */}
        <motion.div className="verdict-hero glass"
          style={{ background: vc.gradient, borderColor: vc.border }}
          initial={{ opacity:0, scale:0.97 }} animate={{ opacity:1, scale:1 }} transition={{ duration:0.4 }}>
          <div className="hero-left">
            <motion.div className="verdict-icon-wrap"
              style={{ background: vc.bg, border:`1px solid ${vc.border}` }}
              initial={{ scale:0.7 }} animate={{ scale:1 }} transition={{ type:'spring', stiffness:300, damping:20, delay:0.15 }}>
              <VIcon size={40} style={{ color: vc.color }}/>
            </motion.div>
            <div>
              <div className="verdict-emoji-label">
                {vc.emoji} <span style={{ color: vc.color }} className="verdict-label">{vc.label}</span>
              </div>
              <p className="verdict-summary">{report.plain_english_summary}</p>
            </div>
          </div>
          <div className="hero-right">
            <RiskRing score={report.risk_score ?? 0} color={vc.color}/>
            <div className="risk-label">Risk Score</div>
          </div>
        </motion.div>

        {/* What To Do */}
        <motion.div className="glass section-card" initial={{ opacity:0, y:16 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.2 }}>
          <h2 className="section-title">What To Do</h2>
          <div className="actions-list">
            {isDanger && (
              <div className="action-card danger-action">
                <div className="action-num" style={{ background:'rgba(239,68,68,0.15)', color:'var(--danger)' }}>!</div>
                <div>
                  <div className="action-text">Report to Cybercrime</div>
                  <a href="https://cybercrime.gov.in" target="_blank" rel="noopener noreferrer" className="action-link">
                    cybercrime.gov.in <ExternalLink size={11}/>
                  </a>
                  <div className="action-sub">National helpline: 1930</div>
                </div>
              </div>
            )}
            {(report.recommended_actions || []).map((action, i) => (
              <div key={i} className="action-card">
                <div className="action-num" style={{ background: vc.bg, color: vc.color }}>{i+1}</div>
                <div className="action-text">{action}</div>
              </div>
            ))}
          </div>
          {isVerify && report.ask_merchant?.length > 0 && (
            <div className="ask-merchant-wrap">
              <div className="ask-merchant-header"><MessageCircle size={14}/> Ask the Merchant</div>
              <div className="question-chips">
                {report.ask_merchant.map((q,i) => <div key={i} className="question-chip">{q}</div>)}
              </div>
            </div>
          )}
        </motion.div>

        {/* Agent Breakdown */}
        <motion.div initial={{ opacity:0, y:16 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.3 }}>
          <h2 className="section-title" style={{ marginBottom:12 }}>Why (Agent Breakdown)</h2>
          <div className="accordions">
            {Object.entries(AGENT_NAMES).map(([key, meta]) => (
              <AccordionCard key={key} emoji={meta.emoji} name={meta.name} model={meta.model}
                narrative={narratives[key]}
                priceIntel={key === 'web_intelligence' ? report.price_intelligence : null}
              />
            ))}
          </div>
        </motion.div>

        {/* Human Gate */}
        <motion.div className="glass section-card" initial={{ opacity:0, y:16 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.4 }}>
          {isVerify && (
            <div className="human-gate verify-gate">
              <h2 className="section-title">Your Decision</h2>
              <p className="gate-sub">We found potential issues. Proceed only after verifying.</p>
              <div className="gate-buttons">
                <button id="verify-first-btn" className="btn-primary" onClick={() => navigate('/')}>✓ I'll Verify First</button>
                <button id="proceed-anyway-btn" className="btn-secondary" onClick={() => alert('Please verify first!')}>Proceed Anyway</button>
              </div>
            </div>
          )}
          {isDanger && (
            <div className="human-gate danger-gate">
              <div className="danger-warning-box">
                <ShieldX size={20}/>
                <div>
                  <div className="danger-warning-title">High Risk — Do Not Pay</div>
                  <div className="danger-warning-sub">To override, type exactly: I UNDERSTAND THE RISK</div>
                </div>
              </div>
              <input id="override-input" type="text" className="form-input override-input"
                placeholder='Type "I UNDERSTAND THE RISK" to unlock override'
                value={overrideInput} onChange={e => setOverride(e.target.value)}/>
              <button id="override-btn" className="btn-danger" disabled={!canOverride}
                onClick={() => alert('Override acknowledged. We strongly advise against this.')}>
                Override (Not Recommended)
              </button>
            </div>
          )}
          {!isDanger && !isVerify && (
            <div className="human-gate safe-gate">
              <CheckCircle2 size={24} style={{ color:'var(--safe)' }}/>
              <p>This payment appears safe. Proceed with confidence.</p>
            </div>
          )}
        </motion.div>

        {/* Footer Actions */}
        <motion.div className="footer-actions" initial={{ opacity:0 }} animate={{ opacity:1 }} transition={{ delay:0.5 }}>
          <button id="share-report-btn" className="btn-secondary" onClick={copyReport}>
            {copied ? <><Check size={15}/> Copied!</> : <><Copy size={15}/> Share Report</>}
          </button>
          <Link to="/" id="check-another-btn" className="btn-secondary">
            <RotateCcw size={15}/> Check Another
          </Link>
          <Link to={`/report/${txn_id}`} className="btn-secondary">
            <ExternalLink size={15}/> Full Report
          </Link>
        </motion.div>

      </div>
    </div>
  )
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)) }
