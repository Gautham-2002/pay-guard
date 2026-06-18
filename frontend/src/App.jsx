import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Shield, History, BookOpen, CreditCard } from 'lucide-react'
import CheckPage from './pages/CheckPage'
import AnalysisPage from './pages/AnalysisPage'
import VerdictPage from './pages/VerdictPage'
import ReportPage from './pages/ReportPage'
import LibraryPage from './pages/LibraryPage'
import HistoryPage from './pages/HistoryPage'
import './App.css'

function Navbar() {
  return (
    <nav className="navbar">
      <div className="navbar-inner">
        <NavLink to="/" className="navbar-logo">
          <div className="logo-icon">
            <Shield size={20} strokeWidth={2.5} />
          </div>
          <span className="logo-text">PayGuard <span className="logo-ai">AI</span></span>
        </NavLink>

        <div className="navbar-links">
          <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <CreditCard size={15} />
            Check Payment
          </NavLink>
          <NavLink to="/library" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <BookOpen size={15} />
            Scam Library
          </NavLink>
          <NavLink to="/history" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <History size={15} />
            History
          </NavLink>
        </div>
      </div>
    </nav>
  )
}

function AnimatedRoutes() {
  const location = useLocation()
  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route path="/" element={<PageWrapper><CheckPage /></PageWrapper>} />
        <Route path="/analysis/:txn_id" element={<PageWrapper><AnalysisPage /></PageWrapper>} />
        <Route path="/verdict/:txn_id" element={<PageWrapper><VerdictPage /></PageWrapper>} />
        <Route path="/report/:txn_id" element={<PageWrapper><ReportPage /></PageWrapper>} />
        <Route path="/library" element={<PageWrapper><LibraryPage /></PageWrapper>} />
        <Route path="/history" element={<PageWrapper><HistoryPage /></PageWrapper>} />
      </Routes>
    </AnimatePresence>
  )
}

function PageWrapper({ children }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="gradient-mesh" />
      <Navbar />
      <main className="main-content">
        <AnimatedRoutes />
      </main>
    </BrowserRouter>
  )
}
