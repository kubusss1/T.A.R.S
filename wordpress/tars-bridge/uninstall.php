<?php
/**
 * Odinstalowanie TARS Bridge: usuwa tabele, opcje, transienty i zadania cron.
 *
 * @package TARS_Bridge
 */

if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
	exit;
}

/**
 * Czyści dane jednej strony (bloga).
 */
function tars_bridge_uninstall_site() {
	global $wpdb;

	// phpcs:disable WordPress.DB.PreparedSQL.InterpolatedNotPrepared, WordPress.DB.DirectDatabaseQuery, WordPress.DB.DirectDatabaseQuery.SchemaChange -- stałe nazwy tabel.
	$wpdb->query( "DROP TABLE IF EXISTS {$wpdb->prefix}tars_hits" );
	$wpdb->query( "DROP TABLE IF EXISTS {$wpdb->prefix}tars_consent" );
	$wpdb->query(
		$wpdb->prepare(
			"DELETE FROM {$wpdb->options} WHERE option_name LIKE %s OR option_name LIKE %s",
			$wpdb->esc_like( '_transient_tars_rl_' ) . '%',
			$wpdb->esc_like( '_transient_timeout_tars_rl_' ) . '%'
		)
	);
	// phpcs:enable

	foreach ( array( 'tars_bridge_api_key', 'tars_bridge_salt', 'tars_bridge_db_version', 'tars_bridge_last_cron', 'tars_bridge_settings' ) as $option ) {
		delete_option( $option );
	}
	delete_transient( 'tars_bridge_ssl' );
	wp_clear_scheduled_hook( 'tars_bridge_prune' );
	wp_clear_scheduled_hook( 'tars_bridge_heartbeat' );
}

if ( is_multisite() && function_exists( 'get_sites' ) ) {
	foreach ( get_sites( array( 'fields' => 'ids', 'number' => 0 ) ) as $tars_blog_id ) {
		switch_to_blog( $tars_blog_id );
		tars_bridge_uninstall_site();
		restore_current_blog();
	}
} else {
	tars_bridge_uninstall_site();
}
