import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronUp, Search, AlertTriangle, CheckCircle2, ArrowRight } from 'lucide-react'
import scamPatterns from '../data/scam_patterns.json'
import './LibraryPage.css'

const ICONS = {
  qr_refund_scam:       '📷',
  olx_buyer_scam:       '🛒',
  fake_customer_support:'📞',
  advance_fee_job_scam: '💼',
  fake_lottery_prize:   '🎰',
  fake_ecommerce_deal:  '🛍️',
}

function ScamCard({ pattern }) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const icon = ICONS[pattern.id] || '⚠️'

  return (
    <motion.div
      className="scam-card glass"
      layout
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <div className="scam-card-header">
        <div className="scam-icon-wrap">{icon}</div>
        <div className="scam-card-info">
          <h3 className="scam-name">{pattern.name}</h3>
          <p className="scam-desc">{pattern.description.slice(0, 120)}...</p>
        </div>
      </div>

      <div className="scam-card-actions">
        <button className="scam-expand-btn" onClick={() => setOpen(o => !o)}>
          {open ? <><ChevronUp size={14}/> Collapse</> : <><ChevronDown size={14}/> Red Flags & What To Do</>}
        </button>
        <button className="btn-secondary scam-cta-btn" onClick={() => navigate('/')}>
          Check a Payment <ArrowRight size={13}/>
        </button>
      </div>

      <AnimatePresence>
        {open && (
          <motion.div
            className="scam-expanded"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
          >
            <div className="scam-columns">
              <div className="scam-column">
                <div className="scam-column-title danger-title">
                  <AlertTriangle size={13}/> Red Flags
                </div>
                <ul className="scam-list">
                  {pattern.red_flags.map((f, i) => (
                    <li key={i} className="scam-list-item danger-item">
                      <span className="scam-list-bullet">⚠</span>
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="scam-column">
                <div className="scam-column-title safe-title">
                  <CheckCircle2 size={13}/> What To Do
                </div>
                <ul className="scam-list">
                  {pattern.what_to_do.map((a, i) => (
                    <li key={i} className="scam-list-item safe-item">
                      <span className="scam-list-bullet">✓</span>
                      {a}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            {pattern.example && (
              <div className="scam-example">
                <div className="scam-example-label">📌 Real Example</div>
                <p>{pattern.example}</p>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

export default function LibraryPage() {
  const [query, setQuery] = useState('')

  const filtered = scamPatterns.filter(p =>
    !query ||
    p.name.toLowerCase().includes(query.toLowerCase()) ||
    p.description.toLowerCase().includes(query.toLowerCase())
  )

  return (
    <div className="library-page">
      <motion.div
        className="library-header"
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <h1 className="library-title">📚 Scam Pattern Library</h1>
        <p className="library-sub">
          Know what fraud looks like before it finds you.
          These are the most common payment scams in India.
        </p>
        <div className="library-search-wrap">
          <Search size={16} className="library-search-icon"/>
          <input
            id="library-search"
            type="text"
            className="form-input library-search"
            placeholder="Search scam patterns..."
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </div>
      </motion.div>

      <div className="scam-grid">
        {filtered.length === 0 ? (
          <div className="no-results">No patterns match your search.</div>
        ) : (
          filtered.map(pattern => <ScamCard key={pattern.id} pattern={pattern}/>)
        )}
      </div>
    </div>
  )
}
