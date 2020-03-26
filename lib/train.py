import tensorflow as tf


class Trainer:
    def __init__(self, generator_clear2fog, generator_fog2clear,
                 discriminator_fog, discriminator_clear, LAMBDA=10,
                 lr=2e-4, beta_1=0.5, normalized_input=True):
        self.LAMBDA = LAMBDA
        self.generator_clear2fog = generator_clear2fog
        self.generator_fog2clear = generator_fog2clear
        self.discriminator_fog = discriminator_fog
        self.discriminator_clear = discriminator_clear
        self.normalized_input = normalized_input
        # Losses
        self.loss_obj = tf.keras.losses.BinaryCrossentropy(from_logits=True)
        self.generator_clear2fog_optimizer = tf.keras.optimizers.Adam(lr, beta_1=beta_1)
        self.generator_fog2clear_optimizer = tf.keras.optimizers.Adam(lr, beta_1=beta_1)
        self.discriminator_fog_optimizer = tf.keras.optimizers.Adam(lr, beta_1=beta_1)
        self.discriminator_clear_optimizer = tf.keras.optimizers.Adam(lr, beta_1=beta_1)
        # Checkpoint Manager
        self.weights_path = None
        self.tensorboard_base_logdir = 'tensorboard_logs'
        self.total_epochs = 0
        self.image_log_path = 'image_logs'
        self.config_path = 'trainer_config.json'
        self.tensorboard_current_logdir = None
        # TODO: add save_config and load_config methods
        # - config contains: all directories + total_epochs
        # - instead of storing summary_writers as class variables, store tensorboard_current_logdir
        # - in load_config, an option will be to load tensorboard_logdir or not
        # - add class variable: config log
        # - pass a parameter that allows to save config on each epoch end

    def save_config(self):
        import json
        import os
        from . import tools
        config = {
            'weights_path': self.weights_path,
            'tensorboard_base_logdir': self.tensorboard_base_logdir,
            'tensorboard_current_logdir': self.tensorboard_current_logdir,
            'total_epochs': self.total_epochs,
            'image_log_path': self.image_log_path,
        }

        # create parent path recursively
        tools.create_dir(os.path.dirname(self.config_path))
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2)
        print("Trainer config saved in {}".format(self.config_path))

    def load_config(self, load_tensorboard_current_logdir=True):
        import json
        import os
        if not os.path.exists(self.config_path):
            print("Config path doesn't exist. Ignoring load config.")
            return

        with open(self.config_path, 'r') as f:
            config = json.load(f)
        if 'weights_path' in config:
            self.weights_path = config['weights_path']
        if 'tensorboard_base_logdir' in config:
            self.tensorboard_base_logdir = config['tensorboard_base_logdir']
        if load_tensorboard_current_logdir and 'tensorboard_current_logdir' in config:
            self.tensorboard_current_logdir = config['tensorboard_current_logdir']
        if 'total_epochs' in config:
            self.total_epochs = config['total_epochs']
        if 'image_log_path' in config:
            self.image_log_path = config['image_log_path']

        print("Trainer config loaded from {}".format(self.config_path))

    def discriminator_loss(self, real, generated):
        real_loss = self.loss_obj(tf.ones_like(real), real)
        generated_loss = self.loss_obj(tf.zeros_like(generated), generated)
        total_disc_loss = real_loss + generated_loss
        return total_disc_loss * 0.5

    def generator_loss(self, generated):
        return self.loss_obj(tf.ones_like(generated), generated)

    def calc_cycle_loss(self, real_image, cycled_image):
        loss1 = tf.reduce_mean(tf.abs(real_image - cycled_image))
        return self.LAMBDA * loss1

    def identity_loss(self, real_image, same_image):
        loss = tf.reduce_mean(tf.abs(real_image - same_image))
        return self.LAMBDA * 0.5 * loss

    def get_models_and_paths(self):
        import os
        generator_clear2fog_weights_path = os.path.join(self.weights_path, 'generator_clear2fog.h5')
        generator_fog2clear_weights_path = os.path.join(self.weights_path, 'generator_fog2clear.h5')
        discriminator_clear_weights_path = os.path.join(self.weights_path, 'discriminator_clear.h5')
        discriminator_fog_weights_path = os.path.join(self.weights_path, 'discriminator_fog.h5')
        models = [self.generator_clear2fog,
                  self.generator_fog2clear,
                  self.discriminator_clear,
                  self.discriminator_fog]
        paths = [generator_clear2fog_weights_path,
                 generator_fog2clear_weights_path,
                 discriminator_clear_weights_path,
                 discriminator_fog_weights_path]
        return models, paths

    def configure_checkpoint(self, weights_path):
        import os
        from . import tools
        self.weights_path = weights_path
        models, paths = self.get_models_and_paths()
        tools.create_dir(weights_path)
        for model, path in zip(models, paths):
            if os.path.isfile(path):
                model.load_weights(path)
                print("Weights loaded: {}".format(path))
            else:
                print("Not found: {}".format(path))

    def save_weights(self):
        models, paths = self.get_models_and_paths()
        for model, path in zip(models, paths):
            model.save_weights(path)

    @tf.function
    def train_step(self, real_clear, real_fog):
        # persistent is set to True because the tape is used more than
        # once to calculate the gradients.
        with tf.GradientTape(persistent=True) as tape:
            # Generator G translates X -> Y
            # Generator F translates Y -> X.
            fake_fog = self.generator_clear2fog(real_clear, training=True)
            cycled_clear = self.generator_fog2clear(fake_fog, training=True)

            fake_clear = self.generator_fog2clear(real_fog, training=True)
            cycled_fog = self.generator_clear2fog(fake_clear, training=True)

            # same_x and same_y are used for identity loss.
            same_clear = self.generator_fog2clear(real_clear, training=True)
            same_fog = self.generator_clear2fog(real_fog, training=True)

            disc_real_clear = self.discriminator_clear(real_clear, training=True)
            disc_real_fog = self.discriminator_fog(real_fog, training=True)

            disc_fake_clear = self.discriminator_clear(fake_clear, training=True)
            disc_fake_fog = self.discriminator_fog(fake_fog, training=True)

            # calculate the loss
            gen_clear2fog_loss = self.generator_loss(disc_fake_fog)
            gen_fog2clear_loss = self.generator_loss(disc_fake_clear)

            total_cycle_loss = self.calc_cycle_loss(real_clear, cycled_clear) + self.calc_cycle_loss(real_fog,
                                                                                                     cycled_fog)

            # Total generator loss = adversarial loss + cycle loss
            total_gen_clear2fog_loss = gen_clear2fog_loss + total_cycle_loss + self.identity_loss(real_fog, same_fog)
            total_gen_fog2clear_loss = gen_fog2clear_loss + total_cycle_loss + self.identity_loss(real_clear,
                                                                                                  same_clear)
            disc_clear_loss = self.discriminator_loss(disc_real_clear, disc_fake_clear)
            disc_fog_loss = self.discriminator_loss(disc_real_fog, disc_fake_fog)

        # Calculate the gradients for generator and discriminator
        generator_clear2fog_gradients = tape.gradient(total_gen_clear2fog_loss,
                                                      self.generator_clear2fog.trainable_variables)
        generator_fog2clear_gradients = tape.gradient(total_gen_fog2clear_loss,
                                                      self.generator_fog2clear.trainable_variables)
        discriminator_clear_gradients = tape.gradient(disc_clear_loss,
                                                      self.discriminator_clear.trainable_variables)
        discriminator_fog_gradients = tape.gradient(disc_fog_loss,
                                                    self.discriminator_fog.trainable_variables)

        # Apply the gradients to the optimizer
        self.generator_clear2fog_optimizer.apply_gradients(zip(generator_clear2fog_gradients,
                                                               self.generator_clear2fog.trainable_variables))
        self.generator_fog2clear_optimizer.apply_gradients(zip(generator_fog2clear_gradients,
                                                               self.generator_fog2clear.trainable_variables))
        self.discriminator_clear_optimizer.apply_gradients(zip(discriminator_clear_gradients,
                                                               self.discriminator_clear.trainable_variables))
        self.discriminator_fog_optimizer.apply_gradients(zip(discriminator_fog_gradients,
                                                             self.discriminator_fog.trainable_variables))

        return total_gen_clear2fog_loss, total_gen_fog2clear_loss, disc_clear_loss, disc_fog_loss

    def epoch_callback(self, sample_test, plot_sample_generator, plot_sample_gen_and_disc,
                       save_sample_generator_output, save_sample_gen_and_disc_output):
        if sample_test is None:
            return
        if type(sample_test) is not list and type(sample_test) is not tuple:
            raise Exception("sample_test should be a list or tuple!")
        if len(sample_test) != 2:
            raise Exception("sample_test should contain 2 elements!")

        sample_clear = sample_test[0]
        sample_fog = sample_test[1]
        prediction_clear2fog = self.generator_clear2fog(sample_clear)
        prediction_fog2clear = self.generator_fog2clear(sample_fog)
        discriminator_clear_output = self.discriminator_clear(sample_clear)
        discriminator_fog_output = self.discriminator_fog(sample_fog)
        discriminator_fakeclear_output = self.discriminator_clear(prediction_fog2clear)
        discriminator_fakefog_output = self.discriminator_fog(prediction_clear2fog)
        from . import plot
        import os
        if plot_sample_gen_and_disc or save_sample_gen_and_disc_output:
            plt = plot.plot_generators_and_discriminators_predictions(sample_clear, prediction_clear2fog,
                                                                      sample_fog,
                                                                      prediction_fog2clear,
                                                                      discriminator_clear_output,
                                                                      discriminator_fog_output,
                                                                      discriminator_fakeclear_output,
                                                                      discriminator_fakefog_output,
                                                                      normalized_input=self.normalized_input)
            if save_sample_gen_and_disc_output:
                plt.savefig(
                    os.path.join(self.image_log_path, "gen_and_disc_output_epoch_{}.jpg".format(self.total_epochs)),
                    bbox_inches='tight', pad_inches=0)
            if plot_sample_gen_and_disc:
                plt.show()

        if plot_sample_generator:
            plot.plot_generators_predictions_v2(sample_clear, prediction_clear2fog, sample_fog,
                                                prediction_fog2clear, normalized_input=self.normalized_input).show()
        if save_sample_generator_output:
            img = plot.get_generator_square_image(sample_clear, prediction_clear2fog, sample_fog,
                                                  prediction_fog2clear,
                                                  normalized_input=self.normalized_input)
            tf.io.write_file(
                os.path.join(self.image_log_path, "gen_output_epoch_{}.jpg".format(self.total_epochs)),
                tf.io.encode_jpeg(img))

    def train(self, train_clear, train_fog, epochs=40, epoch_save_rate=1, progress_print_rate=10,
              clear_output_callback=None, use_tensorboard=False, sample_test=None, plot_sample_generator=False,
              plot_sample_gen_and_disc=True, save_sample_generator_output=True, save_sample_gen_and_disc_output=True,
              load_config_first=True, save_config_each_epoch=True):
        from lib.tools import print_with_timestamp
        import time
        import datetime
        import os

        if load_config_first and self.config_path is not None:
            self.load_config()

        # Create image log path if needed
        if save_sample_generator_output or save_sample_gen_and_disc_output:
            from . import tools
            tools.create_dir(self.image_log_path)

        # Configure tensorboard if not already configured
        tensorboard_summary_writer_clear = None
        tensorboard_summary_writer_fog = None
        if use_tensorboard:
            if self.tensorboard_current_logdir is None:
                self.tensorboard_current_logdir = os.path.join(self.tensorboard_base_logdir,
                                                               datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
            tensorboard_logdir_clear = self.tensorboard_current_logdir + "-clear"
            tensorboard_logdir_fog = self.tensorboard_current_logdir + "-fog"
            tensorboard_summary_writer_clear = tf.summary.create_file_writer(logdir=tensorboard_logdir_clear)
            tensorboard_summary_writer_fog = tf.summary.create_file_writer(logdir=tensorboard_logdir_fog)

        length = "Unknown"
        for epoch in range(epochs):
            print_with_timestamp("Starting with epoch {} (total {})".format(epoch + 1,
                                                                            self.total_epochs + 1))
            clear2fog_loss_total = fog2clear_loss_total = disc_clear_loss_total = disc_fog_loss_total = 0
            self.epoch_callback(sample_test, plot_sample_generator, plot_sample_gen_and_disc,
                                save_sample_generator_output, save_sample_gen_and_disc_output)

            dataset = tf.data.Dataset.zip((train_clear, train_fog))
            n = 0
            start = time.time()
            for image_clear, image_fog in dataset:
                # Train Step
                clear2fog_loss, fog2clear_loss, disc_clear_loss, disc_fog_loss = self.train_step(image_clear,
                                                                                                 image_fog)
                # Update Epoch's losses
                clear2fog_loss_total += clear2fog_loss
                fog2clear_loss_total += fog2clear_loss
                disc_clear_loss_total += disc_clear_loss
                disc_fog_loss_total += disc_fog_loss
                # Print Progress
                if n % progress_print_rate == 0:
                    print_with_timestamp('{}/{}'.format(n, length))
                n += 1
            end = time.time()
            length = n
            if clear_output_callback is not None:
                clear_output_callback()

            # Save weights
            if self.weights_path is not None and epoch_save_rate is not None and (
                    epoch + 1) % epoch_save_rate == 0:
                self.save_weights()
                print_with_timestamp('Saving checkpoint for epoch {} (total {}) at {}'.format(epoch + 1,
                                                                                              self.total_epochs + 1,
                                                                                              self.weights_path))
            print_with_timestamp('Time taken for epoch {} (total {})'
                                 ' is {} sec (effective: {} sec)'.format(epoch + 1,
                                                                         self.total_epochs + 1,
                                                                         time.time() - start,
                                                                         end - start))
            print_with_timestamp('clear2fog loss: {}, fog2clear loss: {}\n\tdisc_clear loss: {}, disc_fog loss: {}'
                                 .format(clear2fog_loss_total, fog2clear_loss_total, disc_clear_loss_total,
                                         disc_fog_loss_total))
            # Tensorboard
            if use_tensorboard:
                with tensorboard_summary_writer_clear.as_default():
                    tf.summary.scalar('generator', fog2clear_loss_total, step=self.total_epochs + 1,
                                      description='fog2clear loss')
                    tf.summary.scalar('discriminator', disc_clear_loss_total, step=self.total_epochs + 1,
                                      description='discriminator_clear loss')
                with tensorboard_summary_writer_fog.as_default():
                    tf.summary.scalar('generator', clear2fog_loss_total, step=self.total_epochs + 1,
                                      description='clear2fog loss')
                    tf.summary.scalar('discriminator', disc_fog_loss_total, step=self.total_epochs + 1,
                                      description='discriminator_fog loss')
                    # TODO: Add Graph to tensorboard: https://www.tensorflow.org/tensorboard/graphs

            self.total_epochs += 1
            if save_config_each_epoch:
                self.save_config()


if __name__ == 'main':
    pass
    # TODO: Perform training