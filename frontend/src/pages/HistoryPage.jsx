import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import axios from 'axios'
import { ExternalLink, ShieldCheck, ShieldAlert, ShieldX, AlertTriangle } from 'lucide-react'
import './HistoryPage.css'

const VERDICT_CONFIG = {
  SAFE:   { label:'Safe',    color:'var(--safe)',   bg:'rgba(16,185,129,0.1)',  Icon: ShieldCheck },
  VERIFY: { label:'Verify',  color:'var(--verify)', bg:'rgba(245,158,11,0.1)', Icon: ShieldAlert },
  DANGER: { label:'Danger',  color:'var(--danger)', bg:'rgba(239,68,68,0.1)',  Icon: ShieldX },
}

function StatCard({ label, value, color }) {
  return (
    <div className="stat-card glass">
      <div className="stat-value" style={{ color: color || 'var(--text-primary)' }}>{value ?? '—'}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

function VerdictChip({ verdict }) {
  const vc = VERDICT_CONFIG[verdict]
  if (!vc) return <span className="verdict-chip unknown">{verdict}</span>
  const { Icon } = vc
  return (
    <span className="verdict-chip" style={{ color: vc.color, background: vc.bg, border:`1px solid ${vc.color}33` }}>
      <Icon size={11}/> {vc.label}
    </span>
  )
}

function SkeletonRow() {
  return (
    <div className="history-row skeleton-row">
      {[80, 140, 70, 120, 70, 60].map((w, i) => (
        <div key={i} className="skeleton" style={{ width: w, height: 14, borderRadius: 4 }}/>
      ))}
    </div>
  )
}

export default function HistoryPage() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    axios.get('/api/history?limit=50')
      .then(res => { setData(res.data); setLoading(false) })
      .catch(err => { setError(err.response?.data?.error || err.message); setLoading(false) })
  }, [])

  if (error) return (
    <div className="history-page">
      <div className="glass error-state">
        <AlertTriangle size={28}/>
        <p>{error}</p>
      </div>
    </div>
  )

  const stats = data || {}
  const transactions = data?.transactions || []

  return (
    <div className="history-page">
      <motion.h1
        className="history-title"
        initial={{ opacity:0, y:-10 }}
        animate={{ opacity:1, y:0 }}
      >
        📋 Transaction History
      </motion.h1>

      {/* Stats Bar */}
      <motion.div
        className="stats-bar"
        initial={{ opacity:0, y:10 }}
        animate={{ opacity:1, y:0 }}
        transition={{ delay:0.1 }}
      >
        <StatCard label="Total Checks"    value={loading ? '—' : stats.total_checks} />
        <StatCard label="✅ Safe"          value={loading ? '—' : stats.safe_count}   color="var(--safe)"   />
        <StatCard label="⚠️ Verify"        value={loading ? '—' : stats.verify_count} color="var(--verify)" />
        <StatCard label="🚨 Danger"        value={loading ? '—' : stats.danger_count} color="var(--danger)" />
        <StatCard label="💰 Fraud Avoided" value={loading ? '—' : (stats.total_fraud_avoided || '₹0')} color="var(--accent-light)" />
      </motion.div>

      {/* Table */}
      <motion.div
        className="glass history-table-wrap"
        initial={{ opacity:0, y:12 }}
        animate={{ opacity:1, y:0 }}
        transition={{ delay:0.2 }}
      >
        {loading ? (
          <div className="history-list">
            {[...Array(5)].map((_, i) => <SkeletonRow key={i}/>)}
          </div>
        ) : transactions.length === 0 ? (
          <div className="history-empty">
            <p>No checks yet.</p>
            <Link to="/" className="btn-primary" style={{ marginTop: 12 }}>
              Check Your First Payment
            </Link>
          </div>
        ) : (
          <>
            <div className="history-table-header">
              <span>Date</span>
              <span>Destination</span>
              <span>Amount</span>
              <span>Product</span>
              <span>Verdict</span>
              <span>Actions</span>
            </div>
            <div className="history-list">
              {transactions.map((tx, i) => (
                <motion.div
                  key={tx.txn_id}
                  className="history-row"
                  initial={{ opacity:0, x:-8 }}
                  animate={{ opacity:1, x:0 }}
                  transition={{ delay: i * 0.04 }}
                >
                  <span className="history-date">
                    {tx.created_at ? new Date(tx.created_at).toLocaleDateString('en-IN') : '—'}
                  </span>
                  <span className="history-dest" title={tx.txn_id}>
                    {tx.band_room_id ? `Room: ${tx.band_room_id.slice(0,12)}...` : tx.txn_id.slice(0,16) + '...'}
                  </span>
                  <span className="history-amount">
                    {tx.amount ? `₹${Number(tx.amount).toLocaleString('en-IN')}` : '—'}
                  </span>
                  <span className="history-product">
                    {tx.product_description?.slice(0, 28) || <em className="text-muted">—</em>}
                  </span>
                  <span><VerdictChip verdict={tx.verdict}/></span>
                  <span>
                    <Link to={`/report/${tx.txn_id}`} className="history-view-btn">
                      <ExternalLink size={13}/> Report
                    </Link>
                  </span>
                </motion.div>
              ))}
            </div>
          </>
        )}
      </motion.div>
    </div>
  )
}
