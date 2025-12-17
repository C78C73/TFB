// Discord Widget API Integration
const DISCORD_SERVER_ID = '1374193582763806781';
const WIDGET_API = `https://discord.com/api/guilds/${DISCORD_SERVER_ID}/widget.json`;

// Fetch Discord stats
async function fetchDiscordStats() {
    try {
        console.log('[Discord] Fetching stats from:', WIDGET_API);
        const response = await fetch(WIDGET_API);
        
        if (!response.ok) {
            const errorMsg = `Widget API returned status ${response.status}: ${response.statusText}`;
            console.error('[Discord]', errorMsg);
            throw new Error(errorMsg);
        }
        
        const data = await response.json();
        console.log('[Discord] Successfully fetched data:', {
            members: data.members?.length || 0,
            online: data.presence_count || 0,
            channels: data.channels?.length || 0
        });
        
        updateStats(data);
        
        // Update every 5 minutes to avoid rate limiting
        setTimeout(fetchDiscordStats, 300000);
        
    } catch (error) {
        console.error('[Discord] Failed to fetch stats:', error);
        
        if (window.errorLogger) {
            window.errorLogger.logError({
                type: 'Discord API Error',
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

// Update the stats display
function updateStats(data) {
    try {
        if (!data) {
            throw new Error('No data provided to updateStats');
        }
        
        // Members currently online
        const onlineCount = data.presence_count || 0;
        const onlineElement = document.getElementById('onlineMembers');
        if (onlineElement) {
            onlineElement.textContent = onlineCount;
        } else {
            console.warn('[Discord] Element "onlineMembers" not found on page');
        }
        
        // Count members in game (status = 'online' or 'dnd' or 'idle' with game activity)
        const inGame = data.members ? data.members.filter(member => 
            member.status !== 'offline' && member.game
        ).length : 0;
        const inGameElement = document.getElementById('inGame');
        if (inGameElement) {
            inGameElement.textContent = inGame;
        } else {
            console.warn('[Discord] Element "inGame" not found on page');
        }
        
        // Add pulse animation to show it's live
        document.querySelectorAll('.stat-value').forEach(el => {
            el.style.animation = 'none';
            setTimeout(() => {
                el.style.animation = 'pulse 0.5s ease-out';
            }, 10);
        });
        
        console.log('[Discord] Stats updated successfully');
    } catch (error) {
        console.error('[Discord] Error updating stats:', error);
        if (window.errorLogger) {
            window.errorLogger.logError({
                type: 'Discord Stats Update Error',
                message: error.message,
                context: 'updateStats'
            });
        }
    }
}

// Show error state
function showError() {
    const onlineElement = document.getElementById('onlineMembers');
    const inGameElement = document.getElementById('inGame');
    if (onlineElement) onlineElement.textContent = '--';
    if (inGameElement) inGameElement.textContent = '--';
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
