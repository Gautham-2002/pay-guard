import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import {
  Search, Camera, Globe, Scale,
  CheckCircle2, AlertTriangle, Clock,
  ChevronDown, ChevronUp, Send, Loader2
} from 'lucide-react'
import './AnalysisPage.css'

const AGENTS = [
  {
    id: 'destination_intelligence',
    seq: 1,
    name: 'Destination Intelligence',
    model: 'Featherless AI',
    emoji: '🔍',
    icon: Search,
    desc: 'Analyzing domain, WHOIS, SSL, and digital footprint...'
  },
  {
    id: 'qr_upi_validator',
    seq: 2,
    name: 'QR & UPI Validator',
    model: 'AIML API Vision',
    emoji: '📷',
    icon: Camera,
    desc: 'Decoding QR code and analyzing UPI context...'
  },
  {
    id: 'web_intelligence',
    seq: 3,
    name: 'Web Intelligence',
    model: 'Playwright + Search',
    emoji: '🌐',
    icon: Globe,
    desc: 'Crawling website, checking reviews, verifying pricing...'
  },
  {
    id: 'verdict_synthesis',
    seq: 4,
    name: 'Verdict Synthesis',
    model: 'AIML API',
    emoji: '⚖️',
    icon: Scale,
    desc: 'Synthesizing all findings into a final verdict...'
  },
]

const STATUS_SEQUENCE = {
  agent_1_running: 1,
  agent_2_running: 2,
  agent_3_running: 3,
  agent_4_running: 4,
}

function getAgentStatus(agent, agentUpdates, currentStatus) {
  const agentId = agent.id
  const update = agentUpdates[agentId]
  if (update) return 'complete'
  if (currentStatus === 'complete') return 'complete'

  const runningMap = {
    'agent_1_running': 'destination_intelligence',
    'agent_2_running': 'qr_upi_validator',
    'agent_3_running': 'web_intelligence',
    'agent_4_running': 'verdict_synthesis',
  }

  const currentAgent = runningMap[currentStatus]
  if (currentAgent === agentId) return 'running'
  const currentSeq = STATUS_SEQUENCE[currentStatus] || 0
  if (currentSeq > agent.seq) return 'complete'
  return 'waiting'
}

export default function AnalysisPage() {
  const { txn_id } = useParams()
  const navigate = useNavigate()

  const [agentUpdates, setAgentUpdates] = useState({})
  const [currentStatus, setCurrentStatus] = useState('agent_1_running')
  const [bandMessages, setBandMessages]   = useState([])
  const [feedOpen, setFeedOpen]           = useState(false)
  const [hitlQuestion, setHitlQuestion]   = useState(null)
  const [hitlAnswer, setHitlAnswer]       = useState('')
  const [hitlLoading, setHitlLoading]     = useState(false)
  const [error, setError]                 = useState(null)
  const eventSourceRef = useRef(null)
  const navigatedRef = useRef(false)

  useEffect(() => {
    const goToVerdict = () => {
      if (navigatedRef.current) return
      navigatedRef.current = true
      navigate(`/verdict/${txn_id}`)
    }

    let es = new EventSource(`/api/check/${txn_id}/stream`)
    eventSourceRef.current = es

    es.addEventListener('agent_update', e => {
      const data = JSON.parse(e.data)
      setAgentUpdates(prev => ({
        ...prev,
        [data.agent]: data
      }))
      setBandMessages(prev => [...prev, {
        type: 'agent_update',
        text: `${data.agent}: ${data.status} (risk: ${data.risk_level || 'N/A'})`,
        preview: data.narrative_preview,
        time: new Date().toLocaleTimeString()
      }])
    })

    es.addEventListener('hitl_required', e => {
      const data = JSON.parse(e.data)
      setHitlQuestion(data.question)
      es.close()
    })

    es.addEventListener('complete', () => {
      es.close()
      setCurrentStatus('complete')
      goToVerdict()
    })

    es.addEventListener('error', e => {
      if (e.data) {
        try {
          const data = JSON.parse(e.data)
          setError(data.error || 'Analysis failed')
        } catch {
          setError('Connection error. Please try again.')
        }
      }
      es.close()
    })

    // Also track status for agent card states
    const statusEs = new EventSource(`/api/check/${txn_id}/status`)
    statusEs.onmessage = e => {
      try {
        const data = JSON.parse(e.data)
        setCurrentStatus(data.status)
        if (data.status === 'complete') statusEs.close()
        if (data.status === 'error') statusEs.close()
      } catch {}
    }
    // Add event listeners for all status types
    ;['agent_1_running','agent_2_running','agent_3_running','agent_4_running',
      'hitl_waiting','complete','error'].forEach(evtType => {
      statusEs.addEventListener(evtType, e => {
        try {
          const data = JSON.parse(e.data)
          setCurrentStatus(data.status || evtType)
          if ((data.status || evtType) === 'complete') {
            statusEs.close()
            es.close()
            goToVerdict()
          }
          if ((data.status || evtType) === 'error') {
            setError(data.error || 'Analysis failed')
            statusEs.close()
          }
        } catch {}
      })
    })

    return () => {
      es.close()
      statusEs.close()
    }
  }, [txn_id, navigate])

  async function handleHitlSubmit(e) {
    e.preventDefault()
    if (!hitlAnswer.trim() || hitlLoading) return
    setHitlLoading(true)

    try {
      await axios.post(`/api/check/${txn_id}/respond`, { answer: hitlAnswer })
      setHitlQuestion(null)
      setHitlAnswer('')

      // Reconnect SSE
      const es = new EventSource(`/api/check/${txn_id}/stream`)
      eventSourceRef.current = es

      es.addEventListener('agent_update', e => {
        const data = JSON.parse(e.data)
        setAgentUpdates(prev => ({ ...prev, [data.agent]: data }))
        setBandMessages(prev => [...prev, {
          type: 'agent_update',
          text: `${data.agent}: ${data.status}`,
          time: new Date().toLocaleTimeString()
        }])
      })

      es.addEventListener('complete', e => {
        es.close()
        setCurrentStatus('complete')
        if (!navigatedRef.current) {
          navigatedRef.current = true
          navigate(`/verdict/${txn_id}`)
        }
      })

      es.addEventListener('error', e => {
        if (e.data) {
          try { setError(JSON.parse(e.data).error) } catch {}
        }
        es.close()
      })

    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to submit response')
    } finally {
      setHitlLoading(false)
    }
  }

  return (
    <div className="analysis-page">
      <div className="analysis-container">
        {/* Header */}
        <motion.div
          className="analysis-header"
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <div className="pulsing-shield">
            <div className="shield-ring" />
            <span className="shield-emoji">🛡️</span>
          </div>
          <h1 className="analysis-title">Analyzing your payment...</h1>
          <p className="analysis-sub">
            Our 4-agent AI pipeline is investigating every signal.
            This takes 30–90 seconds.
          </p>
          <div className="txn-badge">TXN: {txn_id}</div>
        </motion.div>

        {/* Agent Timeline */}
        <div className="agent-timeline">
          {AGENTS.map((agent, idx) => {
            const status = getAgentStatus(agent, agentUpdates, currentStatus)
            const update = agentUpdates[agent.id]
            return (
              <motion.div
                key={agent.id}
                className={`agent-card glass ${status}`}
                initial={{ opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.08 }}
              >
                <div className="agent-card-left">
                  <div className={`agent-icon-wrap ${status}`}>
                    {status === 'complete'
                      ? <CheckCircle2 size={20} />
                      : status === 'running'
                        ? <Loader2 size={20} className="spin-icon" />
                        : <agent.icon size={20} />
                    }
                  </div>
                  {idx < AGENTS.length - 1 && <div className={`timeline-line ${status === 'complete' ? 'done' : ''}`} />}
                </div>

                <div className="agent-card-content">
                  <div className="agent-card-top">
                    <div>
                      <div className="agent-name">
                        <span className="agent-emoji">{agent.emoji}</span>
                        {agent.name}
                      </div>
                      <div className="agent-model">{agent.model}</div>
                    </div>
                    <AgentStatusBadge status={status} riskLevel={update?.risk_level} />
                  </div>

                  <AnimatePresence>
                    {status === 'running' && (
                      <motion.p
                        className="agent-desc"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                      >
                        {agent.desc}
                      </motion.p>
                    )}
                    {status === 'complete' && update?.narrative_preview && (
                      <motion.p
                        className="agent-preview"
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                      >
                        {update.narrative_preview}
                        {update.narrative_preview.length >= 148 ? '...' : ''}
                      </motion.p>
                    )}
                    {status === 'waiting' && (
                      <motion.p className="agent-waiting" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                        Waiting for previous agent...
                      </motion.p>
                    )}
                  </AnimatePresence>
                </div>
              </motion.div>
            )
          })}
        </div>

        {/* HITL Question Card */}
        <AnimatePresence>
          {hitlQuestion && (
            <motion.div
              className="glass hitl-card"
              initial={{ opacity: 0, scale: 0.95, y: 16 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
            >
              <div className="hitl-header">
                <AlertTriangle size={20} className="hitl-icon" />
                <span>Agent needs clarification</span>
              </div>
              <p className="hitl-question">{hitlQuestion}</p>
              <form onSubmit={handleHitlSubmit} className="hitl-form">
                <textarea
                  id="hitl-answer"
                  className="form-textarea"
                  placeholder="Your answer..."
                  value={hitlAnswer}
                  onChange={e => setHitlAnswer(e.target.value)}
                  rows={3}
                />
                <button
                  id="hitl-submit-btn"
                  type="submit"
                  className="btn-primary"
                  disabled={!hitlAnswer.trim() || hitlLoading}
                >
                  {hitlLoading
                    ? <><Loader2 size={16} className="spin-icon" /> Submitting...</>
                    : <><Send size={16} /> Submit Answer</>
                  }
                </button>
              </form>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Error state */}
        <AnimatePresence>
          {error && (
            <motion.div
              className="glass error-card"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              <AlertTriangle size={20} />
              <div>
                <p className="error-title">Analysis Error</p>
                <p className="error-msg">{error}</p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Band Room Feed */}
        <motion.div
          className="glass band-feed"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3 }}
        >
          <button
            className="band-feed-toggle"
            onClick={() => setFeedOpen(f => !f)}
          >
            <span>⚡ Band Room Activity</span>
            {feedOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          </button>

          <AnimatePresence>
            {feedOpen && (
              <motion.div
                className="band-feed-content"
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
              >
                {bandMessages.length === 0 ? (
                  <p className="band-empty">Waiting for agent messages...</p>
                ) : (
                  bandMessages.map((msg, i) => (
                    <div key={i} className="band-message">
                      <span className="band-time">{msg.time}</span>
                      <span className="band-text">{msg.text}</span>
                    </div>
                  ))
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </div>
    </div>
  )
}

function AgentStatusBadge({ status, riskLevel }) {
  if (status === 'waiting') {
    return <span className="status-badge waiting"><Clock size={11} /> Waiting...</span>
  }
  if (status === 'running') {
    return <span className="status-badge running"><Loader2 size={11} className="spin-icon" /> Analyzing...</span>
  }
  if (status === 'complete') {
    const risk = riskLevel?.toUpperCase()
    if (risk === 'HIGH' || risk === 'DANGER') {
      return <span className="status-badge flagged"><AlertTriangle size={11} /> Flagged ⚠</span>
    }
    return <span className="status-badge done"><CheckCircle2 size={11} /> Complete ✓</span>
  }
  return null
}
