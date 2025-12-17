// Discord Stats Page - Comprehensive Analytics
const DISCORD_SERVER_ID = '1374193582763806781';
const WIDGET_API = `https://discord.com/api/guilds/${DISCORD_SERVER_ID}/widget.json`;
const UPDATE_INTERVAL = 300000; // 5 minutes
const STORAGE_KEY = 'tfb_discord_stats';

let activityChart = null;
let currentData = null;

// Initialize stats page
document.addEventListener('DOMContentLoaded', () => {
    loadHistoricalData();
    fetchDiscordStats();
    initActivityChart();
    generateHeatmap();
});

// Fetch Discord stats from API
async function fetchDiscordStats() {
    try {
        console.log('[Stats] Fetching Discord data from:', WIDGET_API);
        const response = await fetch(WIDGET_API);
        
        if (!response.ok) {
            const errorMsg = `Widget API returned status ${response.status}: ${response.statusText}`;
            console.error('[Stats]', errorMsg);
            throw new Error(errorMsg);
        }
        
        currentData = await response.json();
        console.log('[Stats] Data received:', {
            members: currentData.members?.length || 0,
            online: currentData.presence_count || 0
        });
        
        // Update all stats sections with error handling for each
        try { updateRealTimeStats(currentData); } catch (e) { console.error('[Stats] updateRealTimeStats failed:', e); }
        try { updateGamingActivity(currentData); } catch (e) { console.error('[Stats] updateGamingActivity failed:', e); }
        try { updateMembersList(currentData); } catch (e) { console.error('[Stats] updateMembersList failed:', e); }
        try { updateHistoricalStats(currentData); } catch (e) { console.error('[Stats] updateHistoricalStats failed:', e); }
        try { updateEngagementMetrics(currentData); } catch (e) { console.error('[Stats] updateEngagementMetrics failed:', e); }
        try { updateServerStatus(currentData); } catch (e) { console.error('[Stats] updateServerStatus failed:', e); }
        try { checkMilestones(currentData); } catch (e) { console.error('[Stats] checkMilestones failed:', e); }
        
        // Save to localStorage for historical tracking
        try {
            saveStatsToHistory(currentData);
        } catch (e) {
            console.error('[Stats] Failed to save to history:', e);
        }
        
        // Update last refresh time
        const lastUpdateEl = document.getElementById('lastUpdate');
        if (lastUpdateEl) {
            lastUpdateEl.textContent = new Date().toLocaleTimeString();
        }
        
        console.log('[Stats] All updates completed successfully');
        
        // Schedule next update
        setTimeout(fetchDiscordStats, UPDATE_INTERVAL);
        
    } catch (error) {
        console.error('[Stats] Critical error fetching Discord stats:', error);
        
        if (window.errorLogger) {
            window.errorLogger.logError({
                type: 'Stats Page Error',
                message: error.message,
                context: 'fetchDiscordStats',
                serverID: DISCORD_SERVER_ID
            });
        }
        
        showError();
        
        // Retry after 1 minute on error
        setTimeout(fetchDiscordStats, 60000);
    }
}

// Update real-time stats section
function updateRealTimeStats(data) {
    const members = data.members || [];
    const onlineCount = data.presence_count || 0;
    
    // Count by status
    const statusCounts = {
        online: members.filter(m => m.status === 'online').length,
        idle: members.filter(m => m.status === 'idle').length,
        dnd: members.filter(m => m.status === 'dnd').length
    };
    
    // Count gaming and voice
    const gamingCount = members.filter(m => m.game).length;
    const voiceCount = data.channels ? data.channels.length : 0;
    
    // Update DOM - statusOnline now shows total online count
    animateValue('statusOnline', onlineCount);
    animateValue('statusIdle', statusCounts.idle);
    animateValue('statusBusy', statusCounts.dnd);
    animateValue('membersGaming', gamingCount);
    animateValue('inVoice', voiceCount);
    
    // Update progress bar (assuming max 200 members)
    const progressPercent = Math.min((onlineCount / 200) * 100, 100);
    const progressBar = document.getElementById('onlineProgress');
    if (progressBar) {
        progressBar.style.width = `${progressPercent}%`;
    }
}

// Update gaming activity section
function updateGamingActivity(data) {
    const members = data.members || [];
    const gamingMembers = members.filter(m => m.game);
    
    // Count games
    const gameCounts = {};
    gamingMembers.forEach(member => {
        const game = member.game.name;
        gameCounts[game] = (gameCounts[game] || 0) + 1;
    });
    
    // Find most popular game
    let popularGame = '--';
    let maxCount = 0;
    for (const [game, count] of Object.entries(gameCounts)) {
        if (count > maxCount) {
            maxCount = count;
            popularGame = game;
        }
    }
    
    // Update popular game
    document.getElementById('popularGame').textContent = popularGame;
    document.getElementById('popularGameCount').textContent = maxCount > 0 ? `${maxCount} players` : '0 players';
    
    // Arma Reforger players
    const armaPlayers = gamingMembers.filter(m => 
        m.game.name.toLowerCase().includes('arma') || 
        m.game.name.toLowerCase().includes('reforger')
    );
    document.getElementById('armaCount').textContent = `${armaPlayers.length} players`;
    document.getElementById('armaPlayers').innerHTML = armaPlayers
        .map(p => `<div>${p.username}</div>`)
        .join('') || '<div>No one playing</div>';
    
    // Battlefield players
    const bfPlayers = gamingMembers.filter(m => 
        m.game.name.toLowerCase().includes('battlefield')
    );
    document.getElementById('bfCount').textContent = `${bfPlayers.length} players`;
    document.getElementById('bfPlayers').innerHTML = bfPlayers
        .map(p => `<div>${p.username}</div>`)
        .join('') || '<div>No one playing</div>';
    
    // Other games
    const otherGames = {};
    gamingMembers.forEach(member => {
        const game = member.game.name;
        const isArma = game.toLowerCase().includes('arma') || game.toLowerCase().includes('reforger');
        const isBF = game.toLowerCase().includes('battlefield');
        
        if (!isArma && !isBF) {
            otherGames[game] = (otherGames[game] || 0) + 1;
        }
    });
    
    const otherGamesHtml = Object.entries(otherGames)
        .map(([game, count]) => `<div class="game-entry">${game} (${count})</div>`)
        .join('') || '<div>No other games</div>';
    document.getElementById('otherGames').innerHTML = otherGamesHtml;
    
    // Check for operation night
    const opDetector = document.getElementById('operationDetector');
    if (maxCount >= 10) {
        opDetector.style.display = 'block';
        document.getElementById('operationText').textContent = 
            `Operation Night! ${maxCount} members playing ${popularGame}!`;
    } else {
        opDetector.style.display = 'none';
    }
}

// Update members list with avatars
function updateMembersList(data) {
    const members = data.members || [];
    const membersGrid = document.getElementById('membersGrid');
    
    if (members.length === 0) {
        membersGrid.innerHTML = '<p>No members online</p>';
        return;
    }
    
    const membersHtml = members.map(member => {
        const statusClass = member.status || 'offline';
        const gameName = member.game ? member.game.name : '';
        
        return `
            <div class="member-card">
                <div class="member-status">
                    <img src="${member.avatar_url}" alt="${member.username}" class="member-avatar">
                    <span class="status-dot ${statusClass}"></span>
                </div>
                <div class="member-name">${member.username}</div>
                ${gameName ? `<div class="member-game">🎮 ${gameName}</div>` : ''}
            </div>
        `;
    }).join('');
    
    membersGrid.innerHTML = membersHtml;
}

// Update historical stats
function updateHistoricalStats(data) {
    const onlineCount = data.presence_count || 0;
    const history = getHistoricalData();
    
    // Calculate peak today
    const today = new Date().toDateString();
    const todayStats = history.filter(s => new Date(s.timestamp).toDateString() === today);
    const peakToday = todayStats.length > 0 ? 
        Math.max(...todayStats.map(s => s.onlineCount), onlineCount) : onlineCount;
    
    // Calculate peak this week
    const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
    const weekStats = history.filter(s => new Date(s.timestamp) >= weekAgo);
    const peakWeek = weekStats.length > 0 ? 
        Math.max(...weekStats.map(s => s.onlineCount), onlineCount) : onlineCount;
    
    // Calculate average
    const recentStats = history.slice(-100); // Last 100 data points
    const avgOnline = recentStats.length > 0 ?
        Math.round(recentStats.reduce((sum, s) => sum + s.onlineCount, 0) / recentStats.length) : onlineCount;
    
    // Find busiest time
    const hourCounts = Array(24).fill(0);
    const hourSamples = Array(24).fill(0);
    history.forEach(stat => {
        const hour = new Date(stat.timestamp).getHours();
        hourCounts[hour] += stat.onlineCount;
        hourSamples[hour]++;
    });
    const hourAverages = hourCounts.map((count, i) => 
        hourSamples[i] > 0 ? count / hourSamples[i] : 0
    );
    const busiestHour = hourAverages.indexOf(Math.max(...hourAverages));
    
    // Convert to 12-hour format (compact)
    const startHour = busiestHour === 0 ? 12 : busiestHour > 12 ? busiestHour - 12 : busiestHour;
    const endHour = (busiestHour + 1) === 0 ? 12 : (busiestHour + 1) > 12 ? (busiestHour + 1) - 12 : (busiestHour + 1);
    const period = busiestHour < 12 ? 'AM' : 'PM';
    const busiestTime = `${startHour}-${endHour} ${period}`;
    
    // Update DOM
    document.getElementById('peakToday').textContent = peakToday;
    document.getElementById('peakWeek').textContent = peakWeek;
    document.getElementById('avgOnline').textContent = avgOnline;
    document.getElementById('busiestTime').textContent = busiestTime;
    
    // Update activity chart
    updateActivityChart(history);
}

// Initialize activity chart
function initActivityChart() {
    const ctx = document.getElementById('activityChart').getContext('2d');
    activityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Online Members',
                data: [],
                borderColor: '#2ecc71',
                backgroundColor: 'rgba(46, 204, 113, 0.1)',
                tension: 0.4,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(255, 255, 255, 0.1)'
                    }
                },
                x: {
                    grid: {
                        color: 'rgba(255, 255, 255, 0.1)'
                    }
                }
            }
        }
    });
}

// Update activity chart with data
function updateActivityChart(history) {
    if (!activityChart) return;
    
    // Last 24 hours of data
    const dayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000);
    const recentHistory = history.filter(s => new Date(s.timestamp) >= dayAgo);
    
    const labels = recentHistory.map(s => {
        const date = new Date(s.timestamp);
        return `${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
    });
    
    const data = recentHistory.map(s => s.onlineCount);
    
    activityChart.data.labels = labels;
    activityChart.data.datasets[0].data = data;
    activityChart.update();
}

// Generate activity heatmap
function generateHeatmap() {
    const heatmap = document.getElementById('activityHeatmap');
    const history = getHistoricalData();
    
    // Create 7 days × 24 hours grid
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const hourData = Array(7).fill(null).map(() => Array(24).fill(0));
    const hourSamples = Array(7).fill(null).map(() => Array(24).fill(0));
    
    // Aggregate data
    history.forEach(stat => {
        const date = new Date(stat.timestamp);
        const day = date.getDay();
        const hour = date.getHours();
        hourData[day][hour] += stat.onlineCount;
        hourSamples[day][hour]++;
    });
    
    // Calculate averages and max
    let maxAvg = 0;
    hourData.forEach((dayData, day) => {
        dayData.forEach((count, hour) => {
            const avg = hourSamples[day][hour] > 0 ? count / hourSamples[day][hour] : 0;
            hourData[day][hour] = avg;
            maxAvg = Math.max(maxAvg, avg);
        });
    });
    
    // Generate HTML
    let heatmapHtml = '<div style="display: grid; gap: 10px;">';
    days.forEach((dayName, day) => {
        heatmapHtml += `<div style="display: grid; grid-template-columns: 50px repeat(24, 1fr); gap: 4px; align-items: center;">`;
        heatmapHtml += `<div style="font-size: 0.8rem; color: var(--text-secondary);">${dayName}</div>`;
        
        for (let hour = 0; hour < 24; hour++) {
            const avg = hourData[day][hour];
            const level = maxAvg > 0 ? Math.min(Math.floor((avg / maxAvg) * 5), 5) : 0;
            heatmapHtml += `<div class="heatmap-cell activity-${level}" title="${dayName} ${hour}:00 - Avg: ${Math.round(avg)}"></div>`;
        }
        
        heatmapHtml += '</div>';
    });
    heatmapHtml += '</div>';
    
    heatmap.innerHTML = heatmapHtml;
}

// Update engagement metrics
function updateEngagementMetrics(data) {
    const onlineCount = data.presence_count || 0;
    const members = data.members || [];
    
    // Growth trend
    const history = getHistoricalData();
    const weekAgo = history.slice(-100);
    
    if (weekAgo.length >= 40) {
        const recentAvg = weekAgo.slice(-20).reduce((sum, s) => sum + s.onlineCount, 0) / 20;
        const olderAvg = weekAgo.slice(0, 20).reduce((sum, s) => sum + s.onlineCount, 0) / 20;
        
        const trendIndicator = document.getElementById('trendIndicator');
        if (trendIndicator) {
            const diff = recentAvg - olderAvg;
            
            if (diff > 5) {
                trendIndicator.className = 'trend-indicator up';
                trendIndicator.innerHTML = '<span class="trend-arrow">📈</span><span class="trend-text">Growing</span>';
            } else if (diff < -5) {
                trendIndicator.className = 'trend-indicator down';
                trendIndicator.innerHTML = '<span class="trend-arrow">📉</span><span class="trend-text">Declining</span>';
            } else {
                trendIndicator.className = 'trend-indicator stable';
                trendIndicator.innerHTML = '<span class="trend-arrow">➡️</span><span class="trend-text">Stable</span>';
            }
        }
    }
}

// Update server status badge
function updateServerStatus(data) {
    const onlineCount = data.presence_count || 0;
    const badge = document.getElementById('serverStatusBadge');
    
    let icon, text, color;
    
    if (onlineCount >= 50) {
        icon = '🔥';
        text = 'Very Active';
        color = '#e74c3c';
    } else if (onlineCount >= 20) {
        icon = '✅';
        text = 'Active';
        color = '#2ecc71';
    } else if (onlineCount >= 5) {
        icon = '🟢';
        text = 'Online';
        color = '#27ae60';
    } else {
        icon = '🌙';
        text = 'Quiet';
        color = '#95a5a6';
    }
    
    badge.innerHTML = `<span class="status-icon" style="animation: none;">${icon}</span><span class="status-text">${text}</span>`;
    badge.style.borderColor = color;
}

// Check for milestones
function checkMilestones(data) {
    const onlineCount = data.presence_count || 0;
    const milestones = [50, 75, 100, 150, 200];
    const banner = document.getElementById('milestoneBanner');
    
    const milestone = milestones.find(m => onlineCount >= m && onlineCount < m + 2);
    
    if (milestone) {
        document.getElementById('milestoneText').textContent = 
            `Milestone Reached! ${milestone} Members Online!`;
        banner.style.display = 'block';
        
        setTimeout(() => {
            banner.style.display = 'none';
        }, 10000);
    }
}

// Save stats to localStorage
function saveStatsToHistory(data) {
    const history = getHistoricalData();
    const newStat = {
        timestamp: Date.now(),
        onlineCount: data.presence_count || 0,
        memberCount: data.members ? data.members.length : 0
    };
    
    history.push(newStat);
    
    // Keep only last 1000 entries
    if (history.length > 1000) {
        history.shift();
    }
    
    localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
}

// Get historical data from localStorage
function getHistoricalData() {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
}

// Load historical data on init
function loadHistoricalData() {
    const history = getHistoricalData();
    if (history.length > 0) {
        generateHeatmap();
    }
}

// Animate number changes
function animateValue(elementId, newValue) {
    const element = document.getElementById(elementId);
    const currentValue = parseInt(element.textContent) || 0;
    
    if (currentValue === newValue) return;
    
    const duration = 500;
    const steps = 20;
    const stepValue = (newValue - currentValue) / steps;
    let currentStep = 0;
    
    const interval = setInterval(() => {
        currentStep++;
        const value = Math.round(currentValue + (stepValue * currentStep));
        element.textContent = value;
        
        if (currentStep >= steps) {
            element.textContent = newValue;
            clearInterval(interval);
        }
    }, duration / steps);
}

// Show error state
function showError() {
    document.getElementById('serverStatusBadge').innerHTML = 
        '<span class="status-icon" style="animation: none;">❌</span><span class="status-text">Widget Not Enabled</span>';
    document.getElementById('lastUpdate').textContent = 'Error - Enable Discord Widget';
}
