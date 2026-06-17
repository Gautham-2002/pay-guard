import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import axios from 'axios'
import { ShieldCheck, ShieldAlert, ShieldX, AlertTriangle, ExternalLink } from 'lucide-react'
import './ReportPage.css'

const VERDICT_CONFIG = {
  SAFE:   { label:'Safe to Pay',  Icon: ShieldCheck, color:'var(--safe)',   bg:'rgba(16,185,129,0.08)',  emoji:'🟢' },
  VERIFY: { label:'Verify First', Icon: ShieldAlert, color:'var(--verify)', bg:'rgba(245,158,11,0.08)',  emoji:'🟡' },
  DANGER: { label:'DO NOT PAY',   Icon: ShieldX,     color:'var(--danger)', bg:'rgba(239,68,68,0.08)',   emoji:'🔴' },
}

const AGENT_NAMES = {
  destination_intelligence: { name:'Destination Intelligence', model:'Featherless AI',      emoji:'🔍' },
  qr_upi_validator:         { name:'QR & UPI Validator',       model:'AIML API Vision',     emoji:'📷' },
  web_intelligence:         { name:'Web Intelligence',          model:'Playwright + Search', emoji:'🌐' },
}

export default function ReportPage() {
  const { txn_id } = useParams()
  const [report, setReport]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    let attempts = 0
    async function fetchReport() {
      while (attempts < 30) {
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
      setError('Report not available.'); setLoading(false)
    }
    fetchReport()
  }, [txn_id])

  if (loading) return (
    <div className="report-page">
      <div className="report-container">
        {[180, 120, 120, 100].map((h,i) => (
          <div key={i} className="skeleton" style={{ height: h, borderRadius: 16, marginBottom: 12 }}/>
        ))}
      </div>
    </div>
  )

  if (error) return (
    <div className="report-page"><div className="report-container">
      <div className="glass error-state">
        <AlertTriangle size={28}/>
        <p>{error}</p>
        <Link to="/" className="btn-primary">Go Home</Link>
      </div>
    </div></div>
  )

  const vc = VERDICT_CONFIG[report.verdict] || VERDICT_CONFIG.VERIFY
  const { Icon: VIcon } = vc
  const narratives = report.agent_narratives || {}
  const date = report.created_at ? new Date(report.created_at).toLocaleString('en-IN') : new Date().toLocaleDateString('en-IN')

  return (
    <div className="report-page">
      <div className="report-container">

        {/* Banner */}
        <div className="report-banner glass">
          <div className="report-banner-left">
            <div className="report-banner-logo">🛡️ PayGuard AI Analysis Report</div>
            <div className="report-banner-meta">
              <span>{date}</span>
              {report.band_room_id && <span className="report-room">Room: {report.band_room_id}</span>}
            </div>
          </div>
          <div className="report-banner-right">
            <Link to={`/verdict/${txn_id}`} className="btn-secondary" style={{ fontSize: 12 }}>
              <ExternalLink size={13}/> View Interactive
            </Link>
          </div>
        </div>

        {/* Verdict Block */}
        <motion.div className="glass report-verdict" style={{ borderColor: `${vc.color}33` }}
          initial={{ opacity:0, y:12 }} animate={{ opacity:1, y:0 }}>
          <div className="rv-icon" style={{ background: vc.bg }}>
            <VIcon size={36} style={{ color: vc.color }}/>
          </div>
          <div className="rv-content">
            <div className="rv-label" style={{ color: vc.color }}>{vc.emoji} {vc.label}</div>
            <div className="rv-score" style={{ color: vc.color }}>Risk Score: {report.risk_score ?? 0}/100</div>
            <p className="rv-summary">{report.plain_english_summary}</p>
          </div>
        </motion.div>

        {/* Recommended Actions */}
        {report.recommended_actions?.length > 0 && (
          <div className="glass report-section">
            <h2 className="report-section-title">Recommended Actions</h2>
            <ol className="report-actions">
              {report.recommended_actions.map((a, i) => (
                <li key={i} className="report-action-item">{a}</li>
              ))}
            </ol>
          </div>
        )}

        {/* Agent Narratives */}
        <div className="glass report-section">
          <h2 className="report-section-title">Agent Analysis</h2>
          {Object.entries(AGENT_NAMES).map(([key, meta]) => (
            narratives[key] && (
              <div key={key} className="report-agent-block">
                <div className="report-agent-header">
                  <span className="report-agent-emoji">{meta.emoji}</span>
                  <div>
                    <div className="report-agent-name">{meta.name}</div>
                    <div className="report-agent-model">{meta.model}</div>
                  </div>
                </div>
                <p className="report-agent-narrative">{narratives[key]}</p>
                {key === 'web_intelligence' && report.price_intelligence && (
                  <div className="report-price-intel">
                    <strong>Price Intelligence:</strong>{' '}
                    {report.price_intelligence.market_price_range && `Market: ${report.price_intelligence.market_price_range}.`}{' '}
                    {report.price_intelligence.anomaly_detected ? '⚠ Price anomaly detected.' : '✓ Price is within market range.'}
                    {report.price_intelligence.notes && ` ${report.price_intelligence.notes}`}
                  </div>
                )}
              </div>
            )
          ))}
        </div>

        {/* Footer */}
        <div className="report-footer">
          <span>Powered by <strong>PayGuard AI</strong></span>
          <Link to="/">payguard.ai</Link>
        </div>

      </div>
    </div>
  )
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)) }
