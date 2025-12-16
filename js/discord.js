// Discord Widget API Integration
const DISCORD_SERVER_ID = '331875336922988545';
const WIDGET_API = `https://discord.com/api/guilds/${DISCORD_SERVER_ID}/widget.json`;

// Fetch Discord stats
async function fetchDiscordStats() {
    try {
        const response = await fetch(WIDGET_API);
        
        if (!response.ok) {
            throw new Error('Widget not enabled or server ID incorrect');
        }
        
        const data = await response.json();
        updateStats(data);
        
        // Update every 5 minutes to avoid rate limiting
        setTimeout(fetchDiscordStats, 300000);
        
    } catch (error) {
        console.error('Error fetching Discord stats:', error);
        showError();
    }
}

// Update the stats display
function updateStats(data) {
    // Total members online
    const onlineCount = data.presence_count || 0;
    document.getElementById('onlineMembers').textContent = onlineCount;
    
    // Total members (visible in widget)
    const totalMembers = data.members ? data.members.length : 0;
    document.getElementById('totalMembers').textContent = totalMembers;
    
    // Count members in game (status = 'online' or 'dnd' or 'idle' with game activity)
    const inGame = data.members ? data.members.filter(member => 
        member.status !== 'offline' && member.game
    ).length : 0;
    document.getElementById('inGame').textContent = inGame;
    
    // Add pulse animation to show it's live
    document.querySelectorAll('.stat-value').forEach(el => {
        el.style.animation = 'none';
        setTimeout(() => {
            el.style.animation = 'pulse 0.5s ease-out';
        }, 10);
    });
}

// Show error state
function showError() {
    document.getElementById('totalMembers').textContent = '--';
    document.getElementById('onlineMembers').textContent = '--';
    document.getElementById('inGame').textContent = '--';
}

// Advanced: Get detailed member list (optional function)
function getOnlineMembers(data) {
    if (!data.members) return [];
    
    return data.members
        .filter(member => member.status !== 'offline')
        .map(member => ({
            username: member.username,
            status: member.status,
            avatar: member.avatar_url,
            game: member.game || null
        }));
}

// Advanced: Get voice channel activity
function getVoiceActivity(data) {
    if (!data.channels) return [];
    
    return data.channels.map(channel => ({
        name: channel.name,
        id: channel.id,
        position: channel.position
    }));
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', fetchDiscordStats);
