<?php
/**
 * Plugin Name:       TARS Bridge
 * Plugin URI:        https://zrobsite.pl
 * Description:       Most między stroną WordPress a panelem TARS (ZrobSite): status strony (aktualizacje, SSL, PHP, WP-Cron) oraz bezcookiesowa analityka odwiedzin i statystyki zgód cookie. Bez zapisywania adresów IP.
 * Version:           1.0.0
 * Requires at least: 5.6
 * Requires PHP:      7.4
 * Author:            ZrobSite
 * Author URI:        https://zrobsite.pl
 * License:           GPL-2.0-or-later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       tars-bridge
 * Domain Path:       /languages
 *
 * @package TARS_Bridge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'TARS_BRIDGE_VERSION', '1.0.0' );
define( 'TARS_BRIDGE_FILE', __FILE__ );
define( 'TARS_BRIDGE_DIR', plugin_dir_path( __FILE__ ) );
define( 'TARS_BRIDGE_URL', plugin_dir_url( __FILE__ ) );

require_once TARS_BRIDGE_DIR . 'includes/class-tars-logic.php';
require_once TARS_BRIDGE_DIR . 'includes/class-tars-db.php';
require_once TARS_BRIDGE_DIR . 'includes/class-tars-status.php';
require_once TARS_BRIDGE_DIR . 'includes/class-tars-rest.php';
require_once TARS_BRIDGE_DIR . 'includes/class-tars-tracker.php';

if ( is_admin() ) {
	require_once TARS_BRIDGE_DIR . 'includes/class-tars-admin.php';
}

register_activation_hook( __FILE__, array( 'TARS_Bridge_DB', 'activate' ) );
register_deactivation_hook( __FILE__, array( 'TARS_Bridge_DB', 'deactivate' ) );

/**
 * Start wtyczki.
 */
function tars_bridge_init() {
	load_plugin_textdomain( 'tars-bridge', false, dirname( plugin_basename( TARS_BRIDGE_FILE ) ) . '/languages' );

	TARS_Bridge_DB::maybe_upgrade();
	TARS_Bridge_DB::register_cron();
	TARS_Bridge_REST::register();
	TARS_Bridge_Tracker::register();

	if ( is_admin() ) {
		TARS_Bridge_Admin::register();
	}
}
add_action( 'plugins_loaded', 'tars_bridge_init' );
