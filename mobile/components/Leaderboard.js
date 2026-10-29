import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { getLeaderboard } from '../utils/api';
import { colors, radius } from '../utils/theme';

const SCOPES = [
  { id: 'weekly', label: 'This week' },
  { id: 'all_time', label: 'All time' },
];
const MEDALS = ['🥇', '🥈', '🥉'];

/**
 * Private friend-crew ranking by Mindful Miles, with each rider's current AI badge.
 *
 * Props
 *   crewCode      string   the crew's shared code (rankings are never public)
 *   currentUser   string   optional, highlights the rider's own row
 *   refreshKey    any      change it (e.g. after finishing a ride) to reload
 *   style         container style
 */
export default function Leaderboard({ crewCode, currentUser, refreshKey, style }) {
  const [scope, setScope] = useState('weekly');
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const mounted = useRef(true);
  const requestId = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(
    async (isPull = false) => {
      if (!crewCode) return;
      const myRequest = ++requestId.current; // ignore stale answers after a quick scope switch
      if (isPull) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const data = await getLeaderboard({ scope, crew: crewCode.trim().toUpperCase() });
        const list = Array.isArray(data) ? data : data && Array.isArray(data.members) ? data.members : [];
        if (mounted.current && myRequest === requestId.current) setEntries(list);
      } catch (err) {
        if (mounted.current && myRequest === requestId.current) setError(err.message || 'Could not load the leaderboard.');
      } finally {
        if (mounted.current && myRequest === requestId.current) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [crewCode, scope]
  );

  useEffect(() => {
    load(false);
  }, [load, refreshKey]);

  if (!crewCode) {
    return (
      <View style={[styles.container, style]}>
        <Text style={styles.title}>Friend Crew</Text>
        <Text style={styles.muted}>Join or create a crew with a shared code to see how your friends are riding.</Text>
      </View>
    );
  }

  const me = currentUser ? currentUser.trim().toLowerCase() : null;

  const renderItem = ({ item }) => {
    const isMe = me && String(item.user_name).toLowerCase() === me;
    return (
      <View style={[styles.row, isMe && styles.rowMe]}>
        <Text style={styles.rank}>{MEDALS[item.rank - 1] || `${item.rank}`}</Text>
        <View style={styles.nameBlock}>
          <Text style={styles.name} numberOfLines={1}>
            {item.user_name}
            {isMe ? ' (you)' : ''}
          </Text>
          {item.badge_title ? (
            <Text style={styles.badge} numberOfLines={1}>
              {item.badge_title}
            </Text>
          ) : null}
        </View>
        <View style={styles.kmBlock}>
          <Text style={styles.km}>{Number(item.total_km).toFixed(1)}</Text>
          <Text style={styles.kmLabel}>mindful km</Text>
        </View>
      </View>
    );
  };

  return (
    <View style={[styles.container, style]}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Crew {crewCode.trim().toUpperCase()}</Text>
        <View style={styles.tabs}>
          {SCOPES.map((s) => (
            <TouchableOpacity
              key={s.id}
              style={[styles.tab, scope === s.id && styles.tabActive]}
              onPress={() => setScope(s.id)}
              accessibilityRole="button"
              accessibilityState={{ selected: scope === s.id }}
            >
              <Text style={[styles.tabText, scope === s.id && styles.tabTextActive]}>{s.label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      {error ? (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity onPress={() => load(false)}>
            <Text style={styles.retry}>Retry</Text>
          </TouchableOpacity>
        </View>
      ) : null}

      {loading && entries.length === 0 ? (
        <ActivityIndicator color={colors.accent} style={{ marginVertical: 24 }} />
      ) : (
        <FlatList
          data={entries}
          keyExtractor={(item) => `${item.rank}-${item.user_name}`}
          renderItem={renderItem}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor={colors.accent} />}
          ListEmptyComponent={
            !error ? (
              <Text style={styles.muted}>
                {scope === 'weekly' ? 'No rides in this crew yet this week. Be the first to roll out!' : 'No rides logged for this crew yet.'}
              </Text>
            ) : null
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { backgroundColor: colors.card, borderRadius: radius.lg, padding: 16, borderWidth: 1, borderColor: colors.border },
  headerRow: { marginBottom: 10 },
  title: { color: colors.text, fontSize: 18, fontWeight: '800', marginBottom: 8 },
  tabs: { flexDirection: 'row' },
  tab: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.cardAlt, marginRight: 8 },
  tabActive: { backgroundColor: colors.calm },
  tabText: { color: colors.text, fontSize: 13, fontWeight: '600' },
  tabTextActive: { color: '#06231a' },
  muted: { color: colors.muted, fontSize: 14, lineHeight: 20, paddingVertical: 8 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, paddingHorizontal: 8, borderRadius: radius.md },
  rowMe: { backgroundColor: colors.cardAlt, borderWidth: 1, borderColor: colors.calm },
  rank: { width: 36, color: colors.text, fontSize: 18, fontWeight: '800', textAlign: 'center' },
  nameBlock: { flex: 1, marginLeft: 8 },
  name: { color: colors.text, fontSize: 16, fontWeight: '700' },
  badge: { color: colors.muted, fontSize: 12, marginTop: 2 },
  kmBlock: { alignItems: 'flex-end', marginLeft: 8 },
  km: { color: colors.text, fontSize: 18, fontWeight: '800' },
  kmLabel: { color: colors.muted, fontSize: 11 },
  errorBox: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 8 },
  errorText: { color: colors.danger, fontSize: 13, flex: 1, paddingRight: 8 },
  retry: { color: colors.accent, fontWeight: '700' },
});
